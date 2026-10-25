import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mxbridge.cli import main
from mxbridge.install import (MARKERS, definition, install, merge, record_target,
                              require_cli, target, targets_from_manifest)
from mxbridge.state import Store
from scripts.install_local import ROOT, parse_args, perform, stage_source
from scripts.update_local import parse_args as update_args, perform as update


def profile(name="bridge-test"):
    return dict(name=name, description="Bridge test profile", prompt="Test only.",
                tools=[], allowedTools=[], resources=[])


class ClientConfigTests(unittest.TestCase):
    def test_claude_merge_keeps_settings_and_other_client_markers(self):
        keep = dict(type="command", command="other-hook", statusMessage=MARKERS["codex"])
        original = dict(permissions={"deny": ["Bash(secret *)"]}, env={"KEEP": "yes"},
                        hooks={"Stop": [{"matcher": "*", "hooks": [keep]}]})
        proposed = definition("/release/bridge.py", client="claude")
        result = merge(original, proposed, client="claude")
        self.assertEqual(result["permissions"], original["permissions"])
        self.assertEqual(result["env"], original["env"])
        self.assertEqual(result["hooks"]["Stop"][0]["hooks"], [keep])
        self.assertEqual(merge(result, proposed, client="claude"), result)
        removed = merge(result, {}, client="claude")
        self.assertEqual(removed["hooks"]["Stop"], original["hooks"]["Stop"])
        self.assertEqual(proposed["hooks"]["PreToolUse"][0]["hooks"][0]["onFailure"], "continue")

    def test_kiro_object_merge_relocation_and_removal(self):
        original = dict(profile(), hooks={"preToolUse": [dict(command="existing-guard", matcher="write")]})
        first = definition("/first/bridge.py", client="kiro")
        result = merge(original, first, client="kiro")
        self.assertEqual(result["tools"], original["tools"])
        self.assertEqual(result["hooks"]["preToolUse"][0], original["hooks"]["preToolUse"][0])
        second = definition("/second path/bridge.py", client="kiro")
        moved = merge(result, second, client="kiro")
        self.assertNotIn("/first/", json.dumps(moved))
        self.assertEqual(merge(moved, second, client="kiro"), moved)
        removed = merge(moved, {}, client="kiro")
        self.assertEqual(removed["hooks"]["preToolUse"], original["hooks"]["preToolUse"])
        self.assertEqual(removed["hooks"]["stop"], [])

    def test_kiro_array_profiles_preserve_other_actions(self):
        keep = dict(name="keep", trigger="Stop", action=dict(type="agent", prompt="Existing workflow"))
        original = dict(profile(), hooks=[keep], permissions={"rules": []},
                        kiroUpgrade={"revision": 2, "fingerprint": "keep", "source": "keep"})
        proposed = definition("/source/bridge.py", client="kiro", kiro_format="v3")
        result = merge(original, proposed, client="kiro", kiro_format="v3")
        self.assertEqual(result["hooks"][0], keep)
        self.assertEqual(merge(result, proposed, client="kiro", kiro_format="v3"), result)
        self.assertEqual(merge(result, {}, client="kiro", kiro_format="v3"), original)
        with self.assertRaises(ValueError):
            merge(original, definition("/x/bridge.py", client="kiro"), client="kiro")

    def test_v3_rejects_unconverted_trust_fields_without_changing_permissions(self):
        proposed = definition("/source/bridge.py", client="kiro", kiro_format="v3")
        for legacy in ("allowedTools", "toolsSettings"):
            original = dict(name="existing", hooks=[], **{legacy: []})
            with self.assertRaisesRegex(ValueError, "skips unconverted"):
                merge(original, proposed, client="kiro", kiro_format="v3")
            self.assertNotIn("permissions", original)
            self.assertEqual(merge(original, {}, client="kiro", kiro_format="v3"), original)
            for invalid in (None, []):
                with self.subTest(legacy=legacy, permissions=invalid):
                    original["permissions"] = invalid
                    with self.assertRaisesRegex(ValueError, "skips unconverted"):
                        merge(original, proposed, client="kiro", kiro_format="v3")
                    self.assertEqual(original["permissions"], invalid)
                    self.assertEqual(merge(original, {}, client="kiro", kiro_format="v3"), original)

    def test_marker_in_an_unrelated_echo_command_is_not_owned(self):
        command = f"echo hook --client kiro --hook-owner {MARKERS['kiro']}"
        original = dict(profile(), hooks={"stop": [{"command": command}]})
        self.assertEqual(merge(original, {}, client="kiro"), original)

    def test_invalid_shapes_do_not_get_replaced(self):
        for value in ([], dict(hooks="bad"), dict(hooks={"Stop": "bad"}),
                      dict(hooks={"Stop": [{"hooks": "bad"}]})):
            with self.subTest(value=value), self.assertRaises(ValueError):
                merge(value, definition("/x/bridge.py", client="claude"), client="claude")

    def test_preview_and_removal_do_not_require_an_installed_client(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/"agent.json"
            config.write_text(json.dumps(profile()))
            before = config.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()), patch(
                    "mxbridge.cli.require_cli", side_effect=AssertionError("Unexpected CLI lookup")):
                self.assertEqual(main(["install-hooks", "--client", "kiro",
                                       "--agent-config", str(config)]), 0)
                config.unlink()
                self.assertEqual(main(["install-hooks", "--client", "kiro", "--agent-config",
                                       str(config), "--remove", "--apply"]), 0)
            self.assertFalse(config.exists())
            self.assertIn(b"bridge-test", before)

    def test_claude_home_override_and_kiro_requires_explicit_profile(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": folder}):
            self.assertEqual(target("claude")["path"], str(Path(folder).resolve()/"settings.json"))
            with self.assertRaisesRegex(ValueError, "--agent-config"):
                target("kiro")
            with self.assertRaises(ValueError):
                target("kiro", agent_config=Path(folder)/"missing.json")

    def test_backups_and_noop_reinstallation_preserve_config_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/"settings.json"
            before = b'{\n  "permissions": {"deny": ["keep"]}\n}\n'
            config.write_bytes(before)
            proposed = definition("/release/bridge.py", client="claude")
            install(config, proposed, True, client="claude")
            installed = config.read_bytes()
            install(config, proposed, True, client="claude")
            backups = list(Path(folder).glob("*.mx-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), before)
            self.assertEqual(config.read_bytes(), installed)

    def test_concurrent_config_edit_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"settings.json"
            path.write_text("{}")
            real_read = Path.read_bytes
            reads = 0
            def read(file):
                nonlocal reads
                reads += 1
                if reads == 2:
                    path.write_text('{"user":"concurrent edit"}')
                return real_read(file)
            with patch("mxbridge.install.Path.read_bytes", autospec=True, side_effect=read):
                with self.assertRaisesRegex(RuntimeError, "changed during install"):
                    install(path, definition("/release/bridge.py", client="claude"), True, client="claude")
            self.assertEqual(json.loads(path.read_text()), {"user": "concurrent edit"})

    def test_claude_version_gate_matches_advisory_failure_support(self):
        for version, supported in (("2.1.294", False), ("2.1.295", True), ("2.1.308.1314", True)):
            runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, f"claude {version}")
            if supported:
                self.assertEqual(require_cli("claude", runner=runner, which=lambda _: "/claude"), "/claude")
            else:
                with self.assertRaisesRegex(ValueError, "2.1.295"):
                    require_cli("claude", runner=runner, which=lambda _: "/claude")

    def test_registered_targets_survive_updates_and_remove_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            prefix = Path(folder)
            release = prefix/"releases/r1"
            release.mkdir(parents=True)
            script = release/"bridge.py"
            script.write_text("# test")
            manifest_path = prefix/"installation.json"
            manifest_path.write_text(json.dumps(dict(codex_home=str(prefix/"codex"), hooks_only=True)))
            selected = target("claude", claude_settings=prefix/"claude/settings.json")
            before = manifest_path.read_bytes()
            record_target(script, selected, apply=False)
            self.assertEqual(manifest_path.read_bytes(), before)
            record_target(script, selected)
            record_target(script, selected)
            targets = targets_from_manifest(json.loads(manifest_path.read_text()))
            self.assertEqual([t["client"] for t in targets], ["codex", "claude"])
            record_target(script, selected, remove=True)
            self.assertEqual(len(targets_from_manifest(json.loads(manifest_path.read_text()))), 1)


class InstalledClientTests(unittest.TestCase):
    def runtime(self, argv, **kwargs):
        # Only the actual agent binary is stubbed. Venv creation, staged Python
        # hooks, configuration writes, and update execution are real.
        if argv[0] in {"fixture-claude", "fixture-kiro"}:
            if argv[1:] == ["--version"]:
                version = "2.1.308" if argv[0] == "fixture-claude" else "2.34.0"
                return subprocess.CompletedProcess(argv, 0, version, "")
            self.assertEqual(argv[1:4], ["agent", "validate", "--path"])
            self.assertIn("hooks", json.loads(Path(argv[4]).read_text()))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.run(argv, **kwargs)

    def which(self, name):
        return {"claude": "fixture-claude", "kiro-cli": "fixture-kiro"}.get(name)

    def test_multi_client_install_and_upgrade_never_modify_codex_settings(self):
        with tempfile.TemporaryDirectory(prefix="mx clients ") as folder:
            base = Path(folder)
            prefix, codex = base/"installed", base/"codex"
            codex.mkdir()
            (codex/"config.toml").write_text("intentionally invalid Codex config")
            claude, kiro = base/"claude-settings.json", base/"kiro-agent.json"
            claude.write_text('{"permissions":{"deny":["keep"]}}')
            kiro.write_text(json.dumps(profile()))
            args = parse_args(["--hooks-only", "--no-downloads", "--prefix", str(prefix),
                "--codex-home", str(codex), "--client", "claude", "--client", "kiro",
                "--claude-settings", str(claude), "--agent-config", str(kiro)])
            with contextlib.redirect_stdout(io.StringIO()):
                perform(args, platform="linux", runner=self.runtime, which=self.which)
            manifest = json.loads((prefix/"installation.json").read_text())
            self.assertEqual({t["client"] for t in manifest["hook_targets"]}, {"claude", "kiro"})
            self.assertEqual((codex/"config.toml").read_text(), "intentionally invalid Codex config")
            self.assertFalse((codex/"hooks.json").exists())
            self.assertEqual(json.loads(claude.read_text())["permissions"], {"deny": ["keep"]})
            self.assertEqual(json.loads(kiro.read_text())["name"], "bridge-test")

            def installer(options, **kwargs):
                return perform(options, which=self.which, **kwargs)
            with contextlib.redirect_stdout(io.StringIO()):
                update(update_args(["--prefix", str(prefix), "--no-downloads"]), platform="linux",
                       runner=self.runtime, installer=installer)
            self.assertFalse((codex/"hooks.json").exists())
            self.assertEqual((codex/"config.toml").read_text(), "intentionally invalid Codex config")
            self.assertEqual(len(json.loads((prefix/"installation.json").read_text())["hook_targets"]), 2)

    def test_client_dry_run_does_not_invoke_agents_or_create_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            agent = base/"agent.json"
            agent.write_text(json.dumps(profile()))
            args = parse_args(["--hooks-only", "--dry-run", "--prefix", str(base/"install"),
                "--client", "claude", "--client", "kiro", "--claude-settings", str(base/"claude.json"),
                "--agent-config", str(agent)])
            with contextlib.redirect_stdout(io.StringIO()):
                perform(args, platform="linux", runner=lambda *_a, **_k: self.fail("Dry run ran a command"))
            self.assertEqual(list(base.iterdir()), [agent])

    @unittest.skipUnless(os.name == "posix", "Generated commands target macOS/Linux")
    def test_exact_generated_commands_handle_quoted_paths_and_broken_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            prefix = base/"source $(touch SHOULD_NOT_EXIST) ; spaces"
            release = stage_source(ROOT, prefix)
            state = base/"state"
            env = dict(os.environ, MX_CODEX_STATE_DIR=str(state))
            for client in ("claude", "kiro"):
                config = definition(release/"bridge.py", client=client)
                event = "agentSpawn" if client == "kiro" else "SessionStart"
                handler = config["hooks"][event][0]
                command = handler["command"] if client == "kiro" else handler["hooks"][0]["command"]
                result = subprocess.run(command, shell=True, executable="/bin/sh", env=env, cwd=base,
                    input=json.dumps(dict(session_id="same", hook_event_name=event)),
                    capture_output=True, text=True, timeout=5)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
                broken = definition("/missing/bridge.py", "/missing/python", client=client)
                handler = broken["hooks"][event][0]
                command = handler["command"] if client == "kiro" else handler["hooks"][0]["command"]
                result = subprocess.run(command, shell=True, executable="/bin/sh", cwd=base,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertEqual({r["client"] for r in Store(state).read()["rows"]}, {"claude", "kiro"})
            self.assertFalse((base/"SHOULD_NOT_EXIST").exists())

    def test_kiro_wrapper_replaces_placeholder_and_preserves_child_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            code = ("import json,subprocess,sys; subprocess.run("
                    "[sys.executable,sys.argv[1],'hook','--client','kiro'],"
                    "input=json.dumps(dict(session_id='wrapped',hook_event_name='agentSpawn')),"
                    "text=True,check=True); sys.exit(7)")
            result = subprocess.run([sys.executable, str(ROOT/"bridge.py"), "--state-dir", folder,
                "run", "--client", "kiro", "--", sys.executable, "-c", code, str(ROOT/"bridge.py")],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 7)
            rows = Store(folder).read()["rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual((rows[0]["client"], rows[0]["session_id"], rows[0]["status"]),
                             ("kiro", "wrapped", "EXIT ERROR"))


if __name__ == "__main__":
    unittest.main()
