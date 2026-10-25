import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mxbridge.focus import bind, read_bindings, remove
from mxbridge.state import apply_event, empty, export_snapshot
from mxbridge.ssh import decode

ROOT = Path(__file__).resolve().parent.parent
ITERM = "12345678-1234-1234-1234-123456789abc"
OTHER_ITERM = "87654321-4321-4321-4321-cba987654321"


class HerdrAttachmentTests(unittest.TestCase):
    def test_local_herdr_records_socket_without_trusting_server_iterm(self):
        state = empty()
        apply_event(state, {"session_id": "chat", "hook_event_name": "SessionStart"},
                    {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/tmp/herdr.sock",
                     "ITERM_SESSION_ID": "obsolete", "MX_CODEX_TTY": "/dev/tty-old"}, 100)
        row = state["rows"][0]
        self.assertEqual((row["herdr_socket"], row["session_id"]), ("/tmp/herdr.sock", "chat"))
        self.assertEqual((row["iterm_id"], row["tty"]), ("", ""))
        self.assertTrue(row["herdr"])

    def test_ssh_and_exports_never_supply_local_socket_targets(self):
        state = empty()
        payload = {"session_id": "chat", "hook_event_name": "SessionStart"}
        env = {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/tmp/private.sock"}
        apply_event(state, payload, dict(env, SSH_CONNECTION="remote"), 100)
        self.assertEqual(state["rows"][0]["herdr_socket"], "")
        apply_event(state, payload, env, 101)
        wire = export_snapshot(state, 102)
        self.assertNotIn("/tmp/private.sock", json.dumps(wire))
        wire["rows"][0]["herdr_socket"] = "/tmp/injected.sock"
        self.assertFalse(decode(json.dumps(wire), 200)[0].get("herdr_socket"))

    def test_resuming_elsewhere_replaces_or_clears_the_socket(self):
        state = empty()
        payload = {"session_id": "chat", "hook_event_name": "SessionStart"}
        for path in ("/tmp/first.sock", "/tmp/second.sock"):
            apply_event(state, payload, {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": path}, 100)
            self.assertEqual(state["rows"][0]["herdr_socket"], path)
        apply_event(state, payload, {"ITERM_SESSION_ID": ITERM}, 101)
        self.assertEqual(state["rows"][0]["herdr_socket"], "")
        self.assertEqual(state["rows"][0]["iterm_id"], ITERM)

    def test_next_hook_populates_pre_upgrade_herdr_rows(self):
        state = empty()
        apply_event(state, {"session_id": "chat", "hook_event_name": "SessionStart"},
                    {"HERDR_ENV": "1"}, 100)
        del state["rows"][0]["herdr_socket"]
        apply_event(state, {"session_id": "chat", "hook_event_name": "UserPromptSubmit"},
                    {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/tmp/herdr.sock"}, 101)
        self.assertEqual(state["rows"][0]["herdr_socket"], "/tmp/herdr.sock")

    def test_invalid_or_nonherdr_socket_is_not_recorded(self):
        for env in ({"HERDR_SOCKET_PATH": "/tmp/herdr.sock"},
                    {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "relative.sock"},
                    {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/tmp/a\nb.sock"}):
            state = empty()
            apply_event(state, {"session_id": "chat", "hook_event_name": "SessionStart"}, env, 100)
            self.assertEqual(state["rows"][0]["herdr_socket"], "")


class HerdrBindingTests(unittest.TestCase):
    def test_bind_rebind_remove_preserves_other_sessions_and_private_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            env = {"ITERM_SESSION_ID": "w0t1p2:" + ITERM}
            bind(folder, "/tmp/first.sock", env=env)
            bind(folder, "/tmp/second.sock", OTHER_ITERM)
            value = bind(folder, "/tmp/first.sock", OTHER_ITERM)
            self.assertEqual(len(value["bindings"]), 2)
            self.assertTrue(all(b["iterm_id"] == OTHER_ITERM for b in value["bindings"]))
            self.assertEqual(remove(folder, "/tmp/first.sock")["bindings"],
                             [{"socket_path": "/tmp/second.sock", "iterm_id": OTHER_ITERM}])
            if os.name == "posix":
                self.assertEqual((Path(folder) / "herdr-focus.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(folder).glob(".mx-*")), [])

    def test_inherited_herdr_or_ssh_id_cannot_be_auto_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            for env in ({"HERDR_ENV": "1"}, {"SSH_CONNECTION": "remote"}):
                with self.assertRaisesRegex(ValueError, "outer local iTerm2"):
                    bind(folder, "/tmp/herdr.sock", env=dict(env, ITERM_SESSION_ID=ITERM))
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertEqual(bind(folder, "/tmp/herdr.sock", ITERM, env={"HERDR_ENV": "1"})
                             ["bindings"][0]["iterm_id"], ITERM)

    def test_bad_identity_or_path_does_not_change_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            bind(folder, "/tmp/herdr.sock", ITERM)
            config = Path(folder) / "herdr-focus.json"
            before = config.read_bytes()
            for path, target in (("relative", ITERM), ("/tmp/a\nb.sock", ITERM),
                                 ("/tmp/x.sock", "not-an-id"), ("/tmp/x.sock", ITERM.replace("-", ""))):
                with self.assertRaises(ValueError):
                    bind(folder, path, target)
                self.assertEqual(config.read_bytes(), before)

    def test_corrupt_duplicate_or_oversize_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "herdr-focus.json"
            item = {"socket_path": "/tmp/herdr.sock", "iterm_id": ITERM}
            for raw in ("broken", "x" * 65537, '{"schema_version":2,"bindings":[]}',
                        json.dumps({"schema_version": 1, "bindings": [item, item]}),
                        json.dumps({"schema_version": 1, "bindings": [None]})):
                config.write_text(raw)
                with self.assertRaises(ValueError):
                    bind(folder, "/tmp/new.sock", OTHER_ITERM)
                self.assertEqual(config.read_text(), raw)

    def test_cli_roundtrip_does_not_change_agent_state(self):
        with tempfile.TemporaryDirectory() as folder:
            cmd = [sys.executable, str(ROOT / "bridge.py"), "--state-dir", folder, "herdr-focus"]
            args = ["bind", "--socket", "/tmp/herdr.sock", "--iterm-id", ITERM]
            result = subprocess.run(cmd + args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            listed = subprocess.run(cmd + ["list"], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(listed.stdout), json.loads(result.stdout))
            removed = subprocess.run(cmd + ["remove", "--socket", "/tmp/herdr.sock"],
                                     capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(removed.stdout)["bindings"], [])
            self.assertFalse((Path(folder) / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
