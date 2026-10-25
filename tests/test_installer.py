import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from scripts.install_local import (ROOT, InstallError, back_up_packaged_plugins, enable_hooks, hooks_enabled_text,
                                  parse_args, perform, source_files, stage_source)


class InstallerTests(unittest.TestCase):
    def test_enables_hooks_without_changing_other_toml_values(self):
        for text in (
            '# retain comment\n[features]\nhooks = false # switch\nother = false\n',
            'features = { hooks = false, other = false }\nlabel="false"\n',
            'features."hooks" = false\nother=false\n',
        ):
            result = hooks_enabled_text(text)
            desired = tomllib.loads(text)
            desired["features"]["hooks"] = True
            self.assertEqual(tomllib.loads(result), desired)
            self.assertEqual(hooks_enabled_text(result), result)
            if "# retain comment" in text:
                self.assertIn("# retain comment", result)

    def test_explicit_hooks_setting_takes_priority_over_legacy_alias(self):
        text = '[features]\nhooks=true\ncodex_hooks=false\n'
        self.assertEqual(hooks_enabled_text(text), text)

    def test_enables_hooks_when_legacy_alias_is_disabled(self):
        for text in ('[features]\ncodex_hooks=false\n', 'features={codex_hooks=false}\n'):
            result = tomllib.loads(hooks_enabled_text(text))
            self.assertTrue(result["features"]["hooks"])
            self.assertFalse(result["features"]["codex_hooks"])

    def test_no_config_edit_when_hooks_default_is_enabled(self):
        for text in ('', 'model="existing"\n', '[features]\nother=false\n'):
            self.assertEqual(hooks_enabled_text(text), text)

    def test_config_backup_keeps_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"config.toml"
            original = b'[features]\r\nhooks=false\r\nother=false\r\n'
            path.write_bytes(original)
            enable_hooks(path)
            backups = list(Path(folder).glob("config.toml.mx-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertTrue(tomllib.loads(path.read_text())["features"]["hooks"])
            enable_hooks(path)
            self.assertEqual(len(list(Path(folder).glob("*.mx-backup-*"))), 1)

    def test_staged_release_is_stable_and_excludes_build_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/"source"
            root.mkdir()
            (root/"bridge.py").write_text("# source")
            (root/"plugin/bin").mkdir(parents=True)
            (root/"plugin/bin/untrusted.dll").write_text("not source")
            prefix = Path(folder)/"install"
            first = stage_source(root, prefix)
            self.assertEqual(first, stage_source(root, prefix))
            self.assertFalse((first/"plugin/bin").exists())
            (root/"bridge.py").write_text("# update")
            second = stage_source(root, prefix)
            self.assertNotEqual(first, second)
            self.assertEqual((first/"bridge.py").read_text(), "# source")

    def test_modified_installed_source_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/"source"
            root.mkdir()
            (root/"bridge.py").write_text("# original")
            prefix = Path(folder)/"install"
            release = stage_source(root, prefix)
            (release/"bridge.py").write_text("# modified")
            with self.assertRaises(InstallError):
                stage_source(root, prefix)

    def test_dry_run_has_no_writes_or_external_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            args = parse_args(["--hooks-only", "--dry-run", "--prefix", str(Path(folder)/"install"),
                               "--codex-home", str(Path(folder)/"codex")])
            with contextlib.redirect_stdout(io.StringIO()):
                perform(args, platform="linux", runner=lambda *_a, **_k: self.fail("Unexpected subprocess"))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_invalid_config_stops_before_installing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            codex = Path(folder)/"codex"
            codex.mkdir()
            (codex/"config.toml").write_text("invalid !!!")
            args = parse_args(["--hooks-only", "--prefix", str(Path(folder)/"install"), "--codex-home", str(codex)])
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(tomllib.TOMLDecodeError):
                perform(args, platform="linux")
            self.assertFalse((Path(folder)/"install").exists())

    def test_hooks_only_install_and_reinstall_with_spaced_paths(self):
        with tempfile.TemporaryDirectory(prefix="mx install ") as folder:
            prefix, codex = Path(folder)/"install folder", Path(folder)/"codex home"
            codex.mkdir()
            herdr = dict(hooks={"SessionStart":[dict(matcher="startup", hooks=[dict(type="command",command="herdr-state.sh")])]})
            (codex/"hooks.json").write_text(json.dumps(herdr))
            (codex/"config.toml").write_text('[features]\nhooks=false\nother=false\n')
            args = parse_args(["--hooks-only", "--no-downloads", "--prefix", str(prefix), "--codex-home", str(codex)])
            with contextlib.redirect_stdout(io.StringIO()):
                perform(args, platform="linux", which=lambda name: "fake-codex" if name == "codex" else None)
            manifest = json.loads((prefix/"installation.json").read_text())
            python, release = manifest["python"], Path(manifest["release"])
            self.assertTrue(manifest["hooks_only"])
            installed = json.loads((codex/"hooks.json").read_text())
            self.assertEqual(installed["hooks"]["SessionStart"][0], herdr["hooks"]["SessionStart"][0])
            command = installed["hooks"]["Stop"][0]["hooks"][0]["command"]
            self.assertIn("venv-3.15", command)
            self.assertIn(str(release), command)
            self.assertTrue(tomllib.loads((codex/"config.toml").read_text())["features"]["hooks"])
            with contextlib.redirect_stdout(io.StringIO()):
                perform(args, platform="linux", which=lambda _name: "fake-codex")
            self.assertEqual(installed, json.loads((codex/"hooks.json").read_text()))
            self.assertEqual(len(list((prefix/"releases").iterdir())), 1)
            proc = subprocess.run([python, str(release/"bridge.py"), "--state-dir", str(Path(folder)/"state"), "demo"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            if os.name == "posix":
                self.assertEqual((prefix.stat().st_mode & 0o777), 0o700)

    def test_missing_codex_fails_without_install_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            args = parse_args(["--hooks-only", "--prefix", str(Path(folder)/"install"), "--codex-home", str(Path(folder)/"codex")])
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(InstallError, "Codex CLI is missing"):
                perform(args, platform="linux", which=lambda _: None)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_previous_bridge_package_is_backed_up(self):
        with tempfile.TemporaryDirectory() as folder:
            plugins, prefix = Path(folder)/"plugins", Path(folder)/"install"
            metadata = plugins/"CodexMx/metadata"
            metadata.mkdir(parents=True)
            prefix.mkdir()
            (metadata/"LoupedeckPackage.yaml").write_text("name: CodexMx\npluginFileName: CodexMxPlugin.dll\n")
            with contextlib.redirect_stdout(io.StringIO()):
                back_up_packaged_plugins(plugins, prefix)
            self.assertFalse((plugins/"CodexMx").exists())
            self.assertEqual(len(list((prefix/"backups").iterdir())), 1)

    def test_unrecognized_plugin_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            plugins, prefix = Path(folder)/"plugins", Path(folder)/"install"
            (plugins/"CodexMx").mkdir(parents=True)
            prefix.mkdir()
            with self.assertRaises(InstallError):
                back_up_packaged_plugins(plugins, prefix)
            self.assertTrue((plugins/"CodexMx").is_dir())

    def test_mac_build_creates_link_in_simulated_home(self):
        with tempfile.TemporaryDirectory(prefix="mx mac ") as folder:
            home = Path(folder)/"home"
            home.mkdir()
            prefix, codex, sdk = home/"install", home/"codex", home/"PluginApi.dll"
            sdk.write_text("SDK fixture, not used by a real compiler")
            args = parse_args(["--no-downloads", "--prefix", str(prefix), "--codex-home", str(codex), "--sdk", str(sdk)])
            def runner(argv, **kwargs):
                if len(argv) > 1 and argv[1] == "build":
                    package = Path(argv[2]).parent/"bin/Release/package/bin"
                    package.mkdir(parents=True)
                    (package/"CodexMxPlugin.dll").write_text("fixture output")
                    return subprocess.CompletedProcess(argv, 0)
                return subprocess.run(argv, **kwargs)
            with contextlib.redirect_stdout(io.StringIO()), patch("scripts.install_local.Path.home", return_value=home), \
                    patch("scripts.install_local.get_dotnet", return_value=str(home/"dotnet")):
                perform(args, platform="darwin", which=lambda _: "fake-codex", runner=runner)
            link = home/"Library/Application Support/Logi/LogiPluginService/Plugins/CodexMxPlugin.link"
            self.assertTrue(link.is_file())
            self.assertTrue((Path(link.read_text().strip())/"bin/CodexMxPlugin.dll").exists())
            manifest = json.loads((prefix/"installation.json").read_text())
            self.assertFalse(manifest["hooks_only"])
            self.assertEqual(manifest["sdk"], str(sdk.resolve()))
            self.assertEqual(manifest["plugin_release"], manifest["release"])

    def test_pet_setup_is_mac_only_and_dry_run_has_no_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            args = parse_args(["--with-pets", "--dry-run", "--prefix", str(Path(folder)/"install"), "--codex-home", str(Path(folder)/"codex")])
            with self.assertRaisesRegex(InstallError,"belong on the Mac"):
                perform(args,platform="linux")
            with contextlib.redirect_stdout(io.StringIO()):
                perform(args,platform="darwin",runner=lambda *_a,**_k: self.fail("dry run invoked subprocess"))
            self.assertEqual(list(Path(folder).iterdir()),[])


if __name__ == "__main__":
    unittest.main()
