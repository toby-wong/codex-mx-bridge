import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mxbridge.adapters import normalize
from mxbridge.install import definition, install, require_cli, target, targets_from_manifest
from mxbridge.pi_install import MARKER
from mxbridge.ssh import decode
from mxbridge.state import apply_event, empty, export_snapshot
from scripts.install_local import ROOT, parse_args, perform
from scripts.update_local import parse_args as update_args, perform as update


def observation(**changes):
    return dict(dict(schema_version=1, hook_event_name="session_start", session_id="native-id",
                     session_path="/sessions/pi.jsonl", name="Chat", status="READY",
                     attachment_id="attachment-1", attachment_started_at=100, sequence=1,
                     activity_at=100, created_at=80, mode="tui"), **changes)


class PiStateTests(unittest.TestCase):
    def setUp(self):
        self.state = empty()
        self.env = dict(HERDR_ENV="1", HERDR_SOCKET_PATH="/tmp/pi-herdr.sock", ITERM_SESSION_ID="stale")

    def apply(self, value=None, now=100, **changes):
        return apply_event(self.state, value or observation(**changes), self.env, now, client="pi")

    def test_native_identity_and_resume_do_not_use_child_launch_id(self):
        self.apply(kind="subagent", launch_id="launch-1", agent_role="frontier")
        key = self.state["rows"][0]["key"]
        self.apply(attachment_id="attachment-2", attachment_started_at=110,
                   kind="subagent", launch_id="launch-2", now=110)
        self.assertEqual(len(self.state["rows"]), 1)
        row = self.state["rows"][0]
        self.assertEqual((row["key"], row["session_id"], row["agent_id"]), (key, "native-id", "launch-2"))
        self.assertEqual(row["created_at"], 80)
        self.assertEqual(row["session_path"], "/sessions/pi.jsonl")
        self.assertEqual(row["iterm_id"], "")
        self.assertEqual(row["herdr_socket"], "/tmp/pi-herdr.sock")

    def test_heartbeat_name_and_reload_preserve_recent_activity_and_completion(self):
        self.apply()
        self.apply(hook_event_name="agent_settled", status="TURN STOP", sequence=2, activity_at=105, now=105)
        self.apply(hook_event_name="heartbeat", status="TURN STOP", sequence=3, activity_at=105, now=120)
        self.assertEqual(self.state["rows"][0]["updated_at"], 105)
        self.assertEqual(self.state["rows"][0]["valid_until"], 165)
        self.apply(hook_event_name="session_info_changed", status="TURN STOP",
                   name="Renamed 🐈", sequence=4, activity_at=105, now=121)
        self.apply(attachment_id="reloaded", attachment_started_at=122, reason="reload",
                   activity_at=0, now=122)
        self.apply(attachment_id="reloaded", attachment_started_at=122, hook_event_name="heartbeat",
                   activity_at=0, sequence=2, now=140)
        row = self.state["rows"][0]
        self.assertEqual((row["updated_at"], row["status"]), (105, "TURN STOP"))
        self.assertEqual(row["valid_until"], 185)

    def test_delayed_writer_and_out_of_order_sequence_cannot_reopen_replacement(self):
        self.apply()
        self.apply(hook_event_name="session_shutdown", status="CLOSED", sequence=4, now=110)
        self.assertFalse(self.apply(hook_event_name="heartbeat", status="WORKING", sequence=3, now=111))
        self.assertFalse(self.apply(hook_event_name="heartbeat", status="WORKING", sequence=5, now=112))
        self.apply(attachment_id="new", attachment_started_at=120, now=120)
        self.assertFalse(self.apply(hook_event_name="agent_start", status="WORKING", sequence=100, now=121))
        self.assertEqual(self.state["rows"][0]["pi_attachment"], "new")

    def test_child_association_arrives_in_either_order_without_copying_task_data(self):
        for child_first in (False, True):
            self.state = empty()
            child = observation(session_id="child-native", session_path="/sessions/child.jsonl",
                                kind="subagent", launch_id="child-launch", attachment_id="child")
            parent = observation(hook_event_name="child_started", child=dict(
                session_path="/sessions/child.jsonl", launch_id="child-launch",
                task="DO NOT RETAIN", content="DO NOT RETAIN"))
            for item in ([child, parent] if child_first else [parent, child]):
                self.apply(item)
            row = next(r for r in self.state["rows"] if r["kind"] == "subagent")
            self.assertEqual(row["parent_session_id"], "native-id")
            self.assertEqual(row["parent_session_path"], "/sessions/pi.jsonl")
            self.assertNotIn("DO NOT RETAIN", json.dumps(self.state))

    def test_standalone_child_needs_no_parent_and_rpc_cannot_claim_outer_terminal(self):
        self.apply(kind="subagent", launch_id="child", mode="headless")
        row = self.state["rows"][0]
        self.assertEqual(row["parent_session_path"], "")
        self.assertFalse(row["herdr"])
        self.assertEqual(row["iterm_id"], "")

    def test_path_is_preserved_as_data_across_ssh_and_mac_authority_is_stripped(self):
        self.apply(status="WAITING", kind="subagent", launch_id="child", agent_role="mid")
        raw = export_snapshot(self.state, 101)
        raw["rows"][0].update(iterm_id="injected", herdr_socket="/injected", tty="/dev/ttyX")
        row = decode(json.dumps(raw), 200)[0]
        self.assertEqual((row["client"], row["status"], row["session_path"]),
                         ("pi", "WAITING", "/sessions/pi.jsonl"))
        self.assertEqual(row["agent_role"], "mid")
        self.assertEqual((row["iterm_id"], row["herdr_socket"], row["tty"]), ("", "", ""))

    def test_invalid_identity_and_sequences_fail_without_silent_truncation(self):
        for change in (dict(session_path="../relative"), dict(session_path="/" + "x" * 2048),
                       dict(session_id="x" * 513), dict(sequence=True), dict(sequence=0),
                       dict(activity_at=float("nan")), dict(attachment_started_at=-1),
                       dict(kind="subagent"), dict(status="APPROVAL?"), dict(schema_version=True)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize("pi", observation(**change))
        self.apply()
        raw = export_snapshot(self.state)
        raw["rows"][0]["session_id"] = "x" * 513
        with self.assertRaises(ValueError):
            decode(json.dumps(raw), 100)

    def test_other_clients_and_source_instances_do_not_share_pi_identity(self):
        a = normalize("pi", observation())
        b = normalize("pi", observation(), "another")
        self.assertNotEqual(a.key, b.key)
        apply_event(self.state, dict(session_id="native-id", hook_event_name="SessionStart"), {})
        self.apply()
        self.assertEqual(len(self.state["rows"]), 2)


class PiInstallTests(unittest.TestCase):
    def test_owned_extension_install_update_remove_preserves_other_extensions(self):
        with tempfile.TemporaryDirectory(prefix="mx pi ' ") as folder:
            base = Path(folder)
            selected = target("pi", pi_agent_dir=base)
            path = Path(selected["path"])
            path.parent.mkdir()
            keep = path.parent/"herdr-agent-state.ts"
            keep.write_text("// existing native integration")
            content = definition(ROOT/"bridge.py", client="pi")
            self.assertTrue(content.startswith(MARKER))
            self.assertEqual(install(path, content, client="pi")["changed"], True)
            self.assertFalse(path.exists())
            install(path, content, True, client="pi")
            self.assertFalse(install(path, content, True, client="pi")["changed"])
            changed = definition(ROOT/"bridge.py", client="pi", instance="custom")
            install(path, changed, True, client="pi")
            backups = list(path.parent.glob("*.mx-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), content)
            install(path, {}, True, client="pi")
            self.assertFalse(path.exists())
            self.assertEqual(keep.read_text(), "// existing native integration")

    def test_edited_and_symlinked_extensions_are_not_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"bridge.ts"
            content = definition(ROOT/"bridge.py", client="pi")
            path.write_text(content + "// user edit")
            for proposed in (content, {}):
                with self.assertRaisesRegex(ValueError, "edited"):
                    install(path, proposed, True, client="pi")
            path.unlink()
            original = Path(folder)/"original.ts"
            original.write_text(content)
            path.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "symlink"):
                install(path, content, True, client="pi")
            self.assertEqual(original.read_text(), content)

    def test_version_and_custom_agent_directory(self):
        for version, allowed in (("1.4.9", False), ("1.5.0", True)):
            runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, version)
            if allowed:
                self.assertEqual(require_cli("pi", runner=runner, which=lambda _: "/pi"), "/pi")
            else:
                with self.assertRaisesRegex(ValueError, "1.5.0"):
                    require_cli("pi", runner=runner, which=lambda _: "/pi")
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PI_CODING_AGENT_DIR": folder}):
            self.assertEqual(target("pi")["path"], str(Path(folder).resolve()/"extensions/codex-mx-bridge.ts"))

    def test_real_staged_install_and_upgrade_remember_pi_without_editing_settings(self):
        def runner(argv, **kw):
            if argv[0] == "fixture-pi":
                return subprocess.CompletedProcess(argv, 0, "1.5.0", "")
            return subprocess.run(argv, **kw)
        with tempfile.TemporaryDirectory(prefix="mx pi install ") as folder:
            base = Path(folder)
            agent = base/"pi"
            agent.mkdir()
            settings = agent/"settings.json"
            settings.write_text('{"packages":["keep"],"defaultThinkingLevel":"max"}')
            before = settings.read_bytes()
            prefix = base/"installed"
            args = parse_args(["--hooks-only", "--no-downloads", "--prefix", str(prefix),
                               "--client", "pi", "--pi-agent-dir", str(agent)])
            def installer(options, **kw):
                return perform(options, which=lambda name: "fixture-pi" if name == "pi" else None, **kw)
            with contextlib.redirect_stdout(io.StringIO()):
                installer(args, platform="linux", runner=runner)
                update(update_args(["--prefix", str(prefix), "--no-downloads"]),
                       platform="linux", runner=runner, installer=installer)
            manifest = json.loads((prefix/"installation.json").read_text())
            self.assertEqual([t["client"] for t in targets_from_manifest(manifest)], ["pi"])
            self.assertEqual(settings.read_bytes(), before)
            content = (agent/"extensions/codex-mx-bridge.ts").read_text()
            self.assertIn(manifest["python"], content)
            self.assertIn(manifest["release"], content)
