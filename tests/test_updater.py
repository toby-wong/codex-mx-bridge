import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mxbridge.focus import bind, read_bindings
from scripts.install_local import ROOT, InstallError, parse_args as install_args, perform as install
from scripts.update_local import choose_sdk, parse_args, perform, restart_service

ITERM = "12345678-1234-1234-1234-123456789abc"


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mx upgrade ")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.prefix = self.home / "bridge install"
        self.prefix.mkdir()
        self.codex = self.home / "custom codex"
        self.codex.mkdir()
        self.state = self.home / "state"
        self.state.mkdir()
        self.service = self.home / "LogiPluginService.app"
        self.service.mkdir()
        self.sdk = self.home / "known SDK.dll"
        self.sdk.write_bytes(b"SDK selection fixture")
        self.manifest = dict(version="0.3.0", hooks_only=False, sdk=str(self.sdk),
                             release=str(self.prefix / "releases/previous"),
                             codex_home=str(self.codex), python=sys.executable)
        self.manifest_path = self.prefix / "installation.json"
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.home_patch = patch("scripts.update_local.Path.home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def args(self, *extra):
        return parse_args(["--prefix", str(self.prefix), "--state-dir", str(self.state), *extra])

    def run_update(self, args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return perform(args, platform="darwin", service_app=self.service, **kwargs)

    def tree(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob("*") if p.is_file()}

    def test_prefers_cached_net8_tooling_sdk_and_remembers_explicit_choice(self):
        cached = self.prefix / ("tools/logiplugin/.store/logiplugintool/6.1.4.22672/"
                               "logiplugintool/6.1.4.22672/tools/net8.0/any/PluginApi.dll")
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"cached SDK")
        host = self.service / "Contents/MonoBundle/PluginApi.dll"
        host.parent.mkdir(parents=True)
        host.write_bytes(b"newer host SDK")
        with patch("scripts.update_local.SERVICE_APP", self.service):
            self.assertEqual(choose_sdk(self.prefix, {}), cached)
            self.assertEqual(choose_sdk(self.prefix, self.manifest), self.sdk)
            self.assertEqual(choose_sdk(self.prefix, self.manifest, cached), cached)
        with self.assertRaisesRegex(InstallError, "--sdk"):
            choose_sdk(self.prefix, self.manifest, self.home / "missing.dll")

    def test_dry_run_has_no_writes_builds_or_service_calls(self):
        before = self.tree()
        result = self.run_update(self.args("--dry-run", "--bind-herdr", "/tmp/herdr.sock"),
                                 env={"ITERM_SESSION_ID": ITERM},
                                 runner=lambda *_a, **_k: self.fail("Dry run invoked subprocess"),
                                 reloader=lambda *_a, **_k: self.fail("Dry run restarted service"))
        self.assertEqual(result, 0)
        self.assertEqual(self.tree(), before)

    def test_upgrade_uses_original_codex_home_and_preserves_display_and_other_bindings(self):
        display = self.state / "display.json"
        display.write_text('{"mode":"pet","pet":"my-cat"}')
        bind(self.state, "/tmp/other.sock", ITERM)
        before = self.manifest_path.read_bytes()
        calls = []

        def installer(args, **_kwargs):
            self.assertEqual(args.codex_home, self.codex)
            self.assertEqual(args.prefix, self.prefix)
            self.assertEqual(args.sdk, self.sdk)
            self.assertFalse(args.with_pets)
            self.assertIsNone(args.pet_sheet)
            self.assertIsNone(args.motion)
            self.assertFalse(args.hooks_only)
            calls.append("install")
            return 0

        def reloader(app, **_kwargs):
            self.assertEqual(app, self.service)
            self.assertEqual(len(read_bindings(self.state)["bindings"]), 2)
            calls.append("reload")

        self.run_update(self.args("--bind-herdr", "/tmp/herdr.sock"),
                        installer=installer, reloader=reloader, env={"ITERM_SESSION_ID": ITERM})
        self.assertEqual(calls, ["install", "reload"])
        self.assertEqual(display.read_text(), '{"mode":"pet","pet":"my-cat"}')
        backups = list(self.prefix.glob("installation.json.mx-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)

    def test_bad_herdr_binding_is_rejected_before_any_install_changes(self):
        before = self.tree()
        with self.assertRaisesRegex(ValueError, "outer local iTerm2"):
            self.run_update(self.args("--bind-herdr", "/tmp/herdr.sock"),
                            env={"HERDR_ENV": "1", "ITERM_SESSION_ID": ITERM},
                            installer=lambda *_a, **_k: self.fail("Installed before validation"))
        self.assertEqual(self.tree(), before)

    def test_failed_build_never_rebinds_or_restarts(self):
        bind(self.state, "/tmp/herdr.sock", ITERM)
        binding_before = (self.state / "herdr-focus.json").read_bytes()
        manifest_before = self.manifest_path.read_bytes()

        def fail(*_args, **_kwargs):
            raise subprocess.CalledProcessError(1, ["dotnet", "build"])

        with self.assertRaises(subprocess.CalledProcessError):
            self.run_update(self.args("--bind-herdr", "/tmp/herdr.sock", "--iterm-id", ITERM),
                            installer=fail, reloader=lambda *_a, **_k: self.fail("Restart after build failure"))
        self.assertEqual(self.manifest_path.read_bytes(), manifest_before)
        self.assertEqual((self.state / "herdr-focus.json").read_bytes(), binding_before)

    def test_no_restart_and_reload_failure_report_separately(self):
        self.run_update(self.args("--no-restart"), installer=lambda *_a, **_k: 0,
                        reloader=lambda *_a, **_k: self.fail("Restart was disabled"))

        def fail(*_args, **_kwargs):
            raise OSError("fixture reload failure")

        with self.assertRaisesRegex(InstallError, "Files upgraded, but the service reload failed"):
            self.run_update(self.args(), installer=lambda *_a, **_k: 0, reloader=fail)

    def test_missing_manifest_never_turns_upgrade_into_fresh_install(self):
        self.manifest_path.unlink()
        before = self.tree()
        with self.assertRaisesRegex(InstallError, "run bash install.sh first"):
            self.run_update(self.args(), installer=lambda *_a, **_k: self.fail("Unexpected install"))
        self.assertEqual(self.tree(), before)

    def test_home_directory_is_rejected_before_creating_a_backup(self):
        self.home.joinpath("installation.json").write_text(json.dumps(self.manifest))
        before = self.tree()
        with self.assertRaisesRegex(InstallError, "dedicated bridge install"):
            self.run_update(parse_args(["--prefix", str(self.home)]))
        self.assertEqual(self.tree(), before)

    @unittest.skipUnless(os.name == "posix", "Bash updater supports macOS/Linux")
    def test_shell_entrypoint_accepts_spaced_prefix_and_preserves_dry_run(self):
        self.manifest_path.write_text(json.dumps(dict(self.manifest, hooks_only=True)))
        before = self.tree()
        result = subprocess.run(["bash", str(ROOT / "update.sh"), "--prefix=" + str(self.prefix),
                                 "--python=" + sys.executable, "--dry-run", "--no-restart"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No changes made", result.stdout)
        self.assertEqual(self.tree(), before)

    def test_real_hooks_only_upgrade_preserves_user_files(self):
        self.manifest_path.unlink()
        self.codex.joinpath("hooks.json").write_text(json.dumps({
            "description": "mine", "hooks": {"SessionStart": [{"hooks": [
                {"type": "command", "command": "herdr-agent-state.sh"}]}]}}))
        options = install_args(["--hooks-only", "--no-downloads", "--prefix", str(self.prefix),
                                "--codex-home", str(self.codex)])
        with contextlib.redirect_stdout(io.StringIO()):
            install(options, platform="linux", which=lambda _name: "codex")
        hooks_before = self.codex.joinpath("hooks.json").read_bytes()
        self.state.joinpath("display.json").write_text('{"mode":"pet"}')
        self.state.joinpath("state.json").write_text('{"private":"agent-state"}')
        bind(self.state, "/tmp/herdr.sock", ITERM)
        state_before = {p.name: p.read_bytes() for p in self.state.iterdir()}

        def installer(args, **kwargs):
            return install(args, which=lambda _name: "codex", **kwargs)

        with contextlib.redirect_stdout(io.StringIO()):
            result = perform(self.args("--no-downloads"), platform="linux", installer=installer,
                             reloader=lambda *_a, **_k: self.fail("Linux restarted a Mac service"))
        self.assertEqual(result, 0)
        self.assertEqual(self.codex.joinpath("hooks.json").read_bytes(), hooks_before)
        self.assertEqual({p.name: p.read_bytes() for p in self.state.iterdir()}, state_before)
        self.assertTrue(json.loads(self.manifest_path.read_text())["hooks_only"])


class ServiceReloadTests(unittest.TestCase):
    def test_reload_targets_only_current_users_plugin_service_and_tolerates_respawn(self):
        calls = []
        pid_responses = iter(("17\n", "18\n", "18\n"))

        def runner(argv, **_kwargs):
            calls.append(argv)
            stdout = next(pid_responses) if argv[0] == "/usr/bin/pgrep" else ""
            return subprocess.CompletedProcess(argv, 0, stdout=stdout)

        with contextlib.redirect_stdout(io.StringIO()):
            restart_service(Path("/test/LogiPluginService.app"), runner=runner, uid=501,
                            sleep=lambda _seconds: self.fail("Unnecessary wait"))
        self.assertIn(["/usr/bin/pkill", "-TERM", "-x", "-u", "501", "LogiPluginService"], calls)
        self.assertIn(["/usr/bin/open", "-g", "-a", "/test/LogiPluginService.app"], calls)
        self.assertTrue(all("logioptionsplus_agent" not in " ".join(cmd) for cmd in calls))

    def test_unresponsive_old_service_does_not_launch_a_duplicate(self):
        times = iter((0, 11))

        def runner(argv, **_kwargs):
            self.assertNotEqual(argv[0], "/usr/bin/open")
            return subprocess.CompletedProcess(argv, 0, stdout="17\n")

        with self.assertRaisesRegex(InstallError, "did not stop"):
            restart_service(runner=runner, uid=501, now=lambda: next(times), sleep=lambda _: None)

    def test_missing_service_is_started_without_killing_anything(self):
        results = iter(("", "18\n"))

        def runner(argv, **_kwargs):
            self.assertNotEqual(argv[0], "/usr/bin/pkill")
            if argv[0] == "/usr/bin/pgrep":
                stdout = next(results)
                return subprocess.CompletedProcess(argv, 0 if stdout else 1, stdout=stdout)
            return subprocess.CompletedProcess(argv, 0)

        with contextlib.redirect_stdout(io.StringIO()):
            restart_service(runner=runner, uid=501, sleep=lambda _: self.fail("Unexpected wait"))


if __name__ == "__main__":
    unittest.main()
