import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mxbridge.focus import bind, bind_remote, read_bindings, remove, remove_remote
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


class RemoteHerdrBindingTests(unittest.TestCase):
    def test_remote_rebind_and_remove_preserve_local_and_other_remote_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            bind(folder, "/tmp/local.sock", ITERM)
            bind_remote(folder, "desktop", ITERM, ssh_target="workbox",
                        herdr_path="/home/user/.local/bin/herdr")
            bind_remote(folder, "desktop", OTHER_ITERM, remote_session="work")
            bind_remote(folder, "other", OTHER_ITERM)
            value = bind_remote(folder, "desktop", OTHER_ITERM, ssh_target="replacement")
            self.assertEqual(value["bindings"], [{"socket_path": "/tmp/local.sock", "iterm_id": ITERM}])
            self.assertEqual(len(value["remote_bindings"]), 3)
            default = next(b for b in value["remote_bindings"]
                           if b["source"] == "desktop" and b["remote_session"] == "")
            self.assertEqual((default["iterm_id"], default["ssh_target"]), (OTHER_ITERM, "replacement"))
            removed = remove_remote(folder, "desktop")
            self.assertEqual({(b["source"], b["remote_session"]) for b in removed["remote_bindings"]},
                             {("desktop", "work"), ("other", "")})
            self.assertEqual(len(remove_remote(folder, "desktop", "work")["remote_bindings"]), 1)
            self.assertEqual(read_bindings(folder)["bindings"], value["bindings"])
            if os.name == "posix":
                self.assertEqual((Path(folder) / "herdr-focus.json").stat().st_mode & 0o777, 0o600)

    def test_remote_binding_captures_only_the_outer_mac_id(self):
        with tempfile.TemporaryDirectory() as folder:
            value = bind_remote(folder, "desktop", env={"ITERM_SESSION_ID": "w0:" + ITERM})
            self.assertEqual(value["remote_bindings"][0]["iterm_id"], ITERM)
            for env in ({"HERDR_ENV": "1"}, {"SSH_CONNECTION": "remote"}):
                with self.assertRaisesRegex(ValueError, "outer local iTerm2"):
                    bind_remote(folder, "other", env=dict(env, ITERM_SESSION_ID=ITERM))
            self.assertEqual(len(read_bindings(folder)["remote_bindings"]), 1)

    def test_invalid_remote_authority_is_not_written(self):
        with tempfile.TemporaryDirectory() as folder:
            bind_remote(folder, "desktop", ITERM)
            config = Path(folder) / "herdr-focus.json"
            before = config.read_bytes()
            for changes in (dict(source="bad/source"), dict(ssh_target="-oProxyCommand=bad"),
                            dict(ssh_target="user@host; echo bad"), dict(herdr_path="herdr --remote other"),
                            dict(herdr_path="/tmp/a\nb"), dict(remote_session="../other"),
                            dict(remote_session=None), dict(target="bad"), dict(source="x" * 65)):
                args = dict(source="desktop", target=ITERM)
                args.update(changes)
                with self.assertRaises(ValueError):
                    bind_remote(folder, **args)
                self.assertEqual(config.read_bytes(), before)

    def test_corrupt_or_duplicate_remote_bindings_block_local_and_remote_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "herdr-focus.json"
            item = dict(source="desktop", ssh_target="workbox", iterm_id=ITERM)
            for entries in (None, [None], [item, dict(item, remote_session="")],
                            [dict(item, remote_session=None)], [dict(item, ssh_target="bad host")]):
                raw = json.dumps(dict(schema_version=1, bindings=[], remote_bindings=entries))
                config.write_text(raw)
                for change in (lambda: bind(folder, "/tmp/local.sock", ITERM),
                               lambda: bind_remote(folder, "new", ITERM),
                               lambda: remove_remote(folder, "desktop")):
                    with self.assertRaises(ValueError):
                        change()
                    self.assertEqual(config.read_text(), raw)

    def test_remote_session_limit_does_not_prevent_rebinding(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(16):
                bind_remote(folder, f"host-{i}", ITERM)
            with self.assertRaisesRegex(ValueError, "At most 16"):
                bind_remote(folder, "overflow", ITERM)
            self.assertEqual(len(bind_remote(folder, "host-0", OTHER_ITERM)["remote_bindings"]), 16)

    def test_cli_remote_roundtrip_and_local_option_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            cmd = [sys.executable, str(ROOT / "bridge.py"), "--state-dir", folder, "herdr-focus"]
            args = ["bind", "--remote", "desktop", "--ssh-target", "workbox",
                    "--herdr-path", "/home/user/.local/bin/herdr", "--remote-session", "work",
                    "--iterm-id", ITERM]
            result = subprocess.run(cmd + args, capture_output=True, text=True, check=True)
            listed = subprocess.run(cmd + ["list"], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), json.loads(listed.stdout))
            for args in (["bind", "--socket", "/tmp/local.sock", "--iterm-id", ITERM, "--ssh-target", "workbox"],
                         ["remove", "--socket", "/tmp/local.sock", "--remote-session", "work"],
                         ["bind", "--socket", "/tmp/local.sock", "--remote", "desktop"]):
                rejected = subprocess.run(cmd + args, capture_output=True, text=True)
                self.assertEqual(rejected.returncode, 2, rejected.stderr)
            removed = subprocess.run(cmd + ["remove", "--remote", "desktop", "--remote-session", "work"],
                                     capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(removed.stdout)["remote_bindings"], [])
            self.assertFalse((Path(folder) / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
