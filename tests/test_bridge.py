import concurrent.futures
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mxbridge.install import definition, install, merge, MARKER
from mxbridge.ssh import command, collect_once, decode
from mxbridge.state import (Store, apply_event, empty, export_snapshot, run_start,
                            run_update, EVENTS)

ROOT = Path(__file__).resolve().parent.parent


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = empty()

    def event(self, name, sid="s1", **extra):
        payload = dict(hook_event_name=name, session_id=sid, cwd="/private/project", **extra)
        return apply_event(self.state, payload, env={}, now=100)

    def test_full_lifecycle_and_turn_reuse(self):
        for event, status in (("SessionStart", "READY"), ("UserPromptSubmit", "WORKING"),
                              ("PreToolUse", "TOOL"), ("PermissionRequest", "APPROVAL?"),
                              ("PostToolUse", "WORKING"), ("Stop", "TURN STOP"),
                              ("UserPromptSubmit", "WORKING"), ("Interrupt", "INTERRUPTED"),
                              ("SessionEnd", "CLOSED")):
            self.event(event)
            self.assertEqual(self.state["rows"][0]["status"], status)
        self.assertEqual(len(self.state["rows"]), 1)

    def test_prompt_tool_output_and_transcript_are_not_retained(self):
        self.event("UserPromptSubmit", prompt="secret", tool_input={"command":"secret"},
                   transcript_path="/secret/file", last_assistant_message="secret")
        self.assertNotIn("secret", json.dumps(self.state))
        self.assertEqual(self.state["rows"][0]["name"], "project")
        self.assertNotIn("/private", json.dumps(self.state))

    def test_unknown_events_and_missing_session_ignored(self):
        self.assertFalse(self.event("Notification"))
        self.assertFalse(self.event("Stop", sid=""))
        self.assertEqual(self.state["rows"], [])

    def test_subagents_use_agent_id_not_parent_key(self):
        self.event("UserPromptSubmit")
        self.event("SubagentStart", agent_id="a", agent_type="reviewer")
        self.event("SubagentStart", agent_id="b", agent_type="worker")
        self.event("SubagentStop", agent_id="a")
        self.assertEqual([r["status"] for r in self.state["rows"]], ["WORKING", "STOPPED", "WORKING"])
        self.assertFalse(self.event("SubagentStart"))

    def test_compact_start_preserves_working(self):
        self.event("UserPromptSubmit")
        self.event("SessionStart", source="compact")
        self.assertEqual(self.state["rows"][0]["status"], "WORKING")

    def test_late_tool_result_cannot_undo_stop(self):
        self.event("UserPromptSubmit", turn_id="new")
        self.event("Stop", turn_id="new")
        self.assertFalse(self.event("PostToolUse", turn_id="old"))
        self.assertFalse(self.event("PostToolUse", turn_id="new"))
        self.assertEqual(self.state["rows"][0]["status"], "TURN STOP")

    def test_late_result_from_previous_turn_ignored(self):
        self.event("UserPromptSubmit", turn_id="new")
        self.assertFalse(self.event("PostToolUse", turn_id="old"))
        self.assertEqual(self.state["rows"][0]["turn_id"], "new")

    def test_wrapper_replaces_placeholder_and_tracks_exit(self):
        env = {"MX_CODEX_RUN_ID":"run1", "ITERM_SESSION_ID":"w0:abc"}
        run_start(self.state, "run1", "Name", env, 100)
        self.assertEqual(self.state["rows"][0]["status"], "NO HOOKS")
        apply_event(self.state, dict(session_id="s1", hook_event_name="SessionStart"), env, 101)
        self.assertEqual(len(self.state["rows"]), 1)
        run_update(self.state, "run1", 110)
        self.assertEqual(self.state["rows"][0]["valid_until"], 155)
        run_update(self.state, "run1", 120, 1)
        self.assertEqual(self.state["rows"][0]["status"], "EXIT ERROR")

    def test_herdr_and_ssh_never_trust_inherited_iterm(self):
        for env in ({"HERDR_ENV":"1"}, {"SSH_CONNECTION":"x"}):
            s = empty()
            apply_event(s, dict(session_id="s", hook_event_name="SessionStart"),
                        dict(env, ITERM_SESSION_ID="obsolete", MX_CODEX_TTY="/dev/pts/5"), 100)
            self.assertEqual(s["rows"][0]["iterm_id"], "")
            self.assertEqual(s["rows"][0]["tty"], "")

    def test_export_stale_and_relative_clock(self):
        self.event("PreToolUse")
        self.state["rows"][0]["iterm_id"] = "private-id"
        snapshot = export_snapshot(self.state, now=1100)
        self.assertEqual(snapshot["rows"][0]["status"], "STALE")
        self.assertEqual(snapshot["rows"][0]["updated_at"], 1000)
        self.assertEqual(snapshot["rows"][0]["iterm_id"], "")

    def test_closed_rows_remain_closed(self):
        self.event("SessionEnd")
        self.assertEqual(export_snapshot(self.state, now=100000)["rows"][0]["status"], "CLOSED")

    def test_resume_refreshes_attachment_and_clears_old_launcher(self):
        payload = dict(session_id="s", hook_event_name="SessionStart")
        apply_event(self.state, payload, {"ITERM_SESSION_ID":"old", "MX_CODEX_RUN_ID":"old-run"}, 100)
        apply_event(self.state, dict(payload, source="resume"), {"ITERM_SESSION_ID":"new"}, 101)
        row = self.state["rows"][0]
        self.assertEqual((row["iterm_id"], row["run_id"]), ("new", ""))
        apply_event(self.state, dict(payload, source="resume"), {"HERDR_ENV":"1"}, 102)
        self.assertEqual(row["iterm_id"], "")
        self.assertTrue(row["herdr"])


class FileTests(unittest.TestCase):
    def test_atomic_roundtrip_and_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            with store.transaction() as state:
                apply_event(state, dict(session_id="s", hook_event_name="Stop"), {}, 1)
            self.assertEqual(store.read()["revision"], 1)
            self.assertEqual(list(Path(folder).glob(".mx-*")), [])

    def test_corruption_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            store.path.write_text("broken")
            with self.assertRaises(ValueError):
                with store.transaction():
                    pass
            self.assertEqual(store.path.read_text(), "broken")

    def test_concurrent_process_hooks_do_not_lose_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            def invoke(i):
                return subprocess.run([sys.executable, str(ROOT/"bridge.py"), "--state-dir", folder, "hook"],
                    input=json.dumps(dict(session_id=str(i), hook_event_name="SessionStart")),
                    capture_output=True, text=True, timeout=10)
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(invoke, range(18)))
            self.assertTrue(all(r.returncode == 0 and r.stdout.strip() == "{}" for r in results))
            self.assertEqual(len(Store(folder).read()["rows"]), 18)

    def test_hook_failure_is_advisory_json(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.run([sys.executable, str(ROOT/"bridge.py"), "--state-dir", folder, "hook"],
                                  input="invalid", capture_output=True, text=True)
            self.assertEqual((proc.returncode, proc.stdout.strip(), proc.stderr), (0, "{}", ""))
            self.assertTrue((Path(folder)/"hook-error.txt").exists())

    def test_wrapper_records_exit_and_preserves_command_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.run([sys.executable, str(ROOT/"bridge.py"), "--state-dir", folder, "run", "--",
                sys.executable, "-c", "import sys; assert sys.argv[1] == 'space ; $literal'; sys.exit(7)", "space ; $literal"],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 7)
            self.assertEqual(Store(folder).read()["rows"][0]["status"], "EXIT ERROR")


class InstallTests(unittest.TestCase):
    def test_preserves_herdr_and_is_idempotent(self):
        original = {"description":"Existing", "other":"preserve", "hooks":{"SessionStart":[
            {"matcher":"startup", "hooks":[dict(type="command", command="herdr-agent-state.sh")]}]}}
        proposed = definition("/a path/bridge.py", "/usr/bin/python3")
        result = merge(original, proposed)
        self.assertEqual(result["hooks"]["SessionStart"][0], original["hooks"]["SessionStart"][0])
        self.assertEqual(merge(result, proposed), result)
        self.assertEqual(len(proposed["hooks"]), len(EVENTS))
        self.assertEqual(result["other"], "preserve")

    def test_removal_keeps_other_handlers_in_same_group(self):
        original = {"hooks":{"Stop":[{"hooks":[dict(statusMessage=MARKER), dict(command="keep")]}]}}
        self.assertEqual(merge(original, {})["hooks"]["Stop"][0]["hooks"], [dict(command="keep")])

    def test_install_preview_backup_and_relocate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"hooks.json"
            path.write_text('{"hooks":{},"description":"mine"}')
            original = path.read_bytes()
            install(path, definition("/one/bridge.py"), False)
            self.assertEqual(path.read_bytes(), original)
            install(path, definition("/two/bridge.py"), True)
            self.assertEqual(len(list(Path(folder).glob("hooks.json.mx-backup-*"))), 1)
            install(path, definition("/three/bridge.py"), True)
            self.assertNotIn("/two/", path.read_text())
            self.assertEqual(json.loads(path.read_text())["description"], "mine")


class SshTests(unittest.TestCase):
    def test_ssh_command_preserves_remote_quoting_and_host_trust(self):
        args = command("workbox", "/home/me/a path/bridge.py", remote_state="/tmp/status directory")
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("BatchMode=yes", args)
        remote = shlex.split(args[-1])
        self.assertEqual(remote, ["python3", "/home/me/a path/bridge.py", "--state-dir", "/tmp/status directory", "export"])
        with self.assertRaises(ValueError):
            command("-oProxyCommand=bad", "/tmp/bridge.py")

    def fixture(self):
        s = empty()
        apply_event(s, dict(session_id="same-as-local", hook_event_name="PreToolUse"), {}, 100)
        return json.dumps(export_snapshot(s, 101)).encode()

    def test_decode_normalizes_clock_and_drops_focus(self):
        data = json.loads(self.fixture())
        data["rows"][0]["iterm_id"] = "inject"
        row = decode(json.dumps(data), now=10000, elapsed=2)[0]
        self.assertEqual(row["valid_until"], 10897)
        self.assertEqual(row["updated_at"], 9997)
        self.assertEqual(row["iterm_id"], "")

    def test_rejects_invalid_schema_size_and_nan(self):
        for raw in (b"x" * (1024*1024+1), b'{"schema_version":2}',
                    b'{"schema_version":1,"rows":[{"status":"TOOL","key":"a","valid_until":NaN}]}'):
            with self.assertRaises(ValueError):
                decode(raw, 100)

    def test_collection_success_then_disconnect_preserves_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            def runner(argv, **kwargs):
                kwargs["stdout"].write(self.fixture())
                return subprocess.CompletedProcess(argv, 0)
            self.assertTrue(collect_once(store, "linux", ["ssh", "fixture"], runner, lambda: 1000))
            self.assertEqual(len(store.read()["remotes"]["linux"]["rows"]), 1)
            def fail(*_args, **_kwargs):
                raise subprocess.TimeoutExpired("ssh", 12)
            self.assertFalse(collect_once(store, "linux", ["ssh", "fixture"], fail, lambda: 1100))
            cached = store.read()["remotes"]["linux"]
            self.assertEqual(len(cached["rows"]), 1)
            self.assertEqual(cached["received_at"], 1000)
            self.assertIn("TimeoutExpired", cached["error"])


if __name__ == "__main__":
    unittest.main()
