import contextlib
import functools
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from mxbridge import __version__
from mxbridge.distribution import PLUGIN_FILES, validate_plugin
from mxbridge.setup import perform as setup
from scripts.install_local import parse_args, perform, stage_source
from scripts.release import ROOT, archive, check_version, checksum, formula, package


class HomebrewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mx brew test ")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.plugin = self.folder / "plugin"
        for name in PLUGIN_FILES:
            path = self.plugin / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("test plugin fixture: " + name)

    def distribution(self):
        output = self.folder / "artifacts"
        result = package(ROOT, self.plugin, output, "v" + __version__)
        target = self.folder / "cellar"
        target.mkdir()
        with tarfile.open(result) as stream:
            stream.extractall(target, filter="data")
        root = next(target.iterdir())
        (root / "homebrew.json").write_text(json.dumps(
            dict(schema_version=1, python=sys.executable, root=str(root))))
        return root, result

    def test_release_contains_runtime_and_prebuilt_plugin_without_sdk_or_user_art(self):
        root, output = self.distribution()
        self.assertEqual(validate_plugin(root), root / "prebuilt/CodexMx")
        with tarfile.open(output) as stream:
            names = stream.getnames()
        self.assertTrue(any(name.endswith("settings_web/app.js") for name in names))
        self.assertTrue(any(name.endswith("/LICENSE") for name in names))
        self.assertFalse(any("PluginApi.dll" in name or "/docs/assets/" in name or
                             "/test-results/" in name or "homebrew.json" in name for name in names))
        staged = stage_source(root, self.folder / "active")
        self.assertTrue((staged / "prebuilt/CodexMx/bin/CodexMxPlugin.dll").is_file())
        self.assertTrue((staged / "homebrew.json").is_file())
        self.assertEqual(validate_plugin(staged), staged / "prebuilt/CodexMx")

    def test_plugin_tampering_extra_files_and_wrong_version_are_rejected(self):
        root, _ = self.distribution()
        path = root / "prebuilt/CodexMx/bin/CodexMxPlugin.dll"
        before = path.read_bytes()
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum"):
            validate_plugin(root)
        path.write_bytes(before)
        extra = path.with_name("PluginApi.dll")
        extra.write_bytes(b"must not redistribute")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            validate_plugin(root)
        extra.unlink()
        record = json.loads((root / "distribution.json").read_text())
        record["version"] = "999.0.0"
        (root / "distribution.json").write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "version"):
            validate_plugin(root)

    def test_archive_and_formula_are_reproducible_and_validate_inputs(self):
        source = self.folder / "source"
        source.mkdir()
        (source / "a").write_text("content")
        one, two = self.folder / "one.tar.gz", self.folder / "two.tar.gz"
        archive(source, one)
        os.utime(source / "a", (100, 200))
        archive(source, two)
        self.assertEqual(checksum(one), checksum(two))
        text = formula("https://github.com/owner/repo/releases/download/v1.0.0/file.tar.gz", "a" * 64)
        self.assertNotIn("@@", text)
        self.assertIn('depends_on "pillow"', text)
        self.assertIn('version "' + __version__ + '"', text)
        for url in ('https://example.com/"injected', "https://example.com/file\nother", "javascript:bad"):
            with self.assertRaises(ValueError):
                formula(url, "a" * 64)
        with self.assertRaises(ValueError):
            check_version("v999.0.0")

    def test_prebuilt_setup_preserves_settings_needs_no_dotnet_and_survives_cellar_removal(self):
        root, _ = self.distribution()
        home = self.folder / "home"
        home.mkdir()
        prefix, codex = home / "active", home / ".codex"
        codex.mkdir()
        original = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "herdr-observe"}]}]}}
        (codex / "hooks.json").write_text(json.dumps(original))
        config = home / ".config/codex-mx-bridge/display.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"preserve":"pet assignments"}')
        sdk = home / "PluginApi.dll"
        sdk.write_text("host marker; never passed to a compiler")
        args = parse_args(["--prefix", str(prefix), "--codex-home", str(codex), "--sdk", str(sdk)])
        args.no_restart = True
        installer = functools.partial(perform, which=lambda name: "fake-codex")
        with patch("pathlib.Path.home", return_value=home), \
                patch("scripts.install_local.get_dotnet", side_effect=AssertionError("No build allowed")), \
                contextlib.redirect_stdout(io.StringIO()):
            setup(args, root=root, platform="darwin", installer=installer)
            first = (codex / "hooks.json").read_bytes()
            setup(args, root=root, platform="darwin", installer=installer)
        self.assertEqual((codex / "hooks.json").read_bytes(), first)
        self.assertEqual(config.read_text(), '{"preserve":"pet assignments"}')
        self.assertEqual(json.loads(first)["hooks"]["SessionStart"][0], original["hooks"]["SessionStart"][0])
        manifest = json.loads((prefix / "installation.json").read_text())
        self.assertEqual(manifest["distribution"], "homebrew")
        self.assertTrue(manifest["prebuilt_plugin"])
        self.assertFalse((prefix / "venv-3.15").exists())
        self.assertTrue((home / "Applications/Codex MX Bridge.app/Contents/Info.plist").is_file())
        shutil.rmtree(root)
        release = Path(manifest["release"])
        self.assertTrue((release / "prebuilt/CodexMx/bin/CodexMxPlugin.dll").is_file())
        state = self.folder / "state"
        run = subprocess.run([sys.executable, str(release / "bridge.py"), "--state-dir", str(state), "hook"],
                             input='{"session_id":"brew-smoke","hook_event_name":"SessionStart"}',
                             capture_output=True, text=True, check=True)
        self.assertEqual(run.stdout.strip(), "{}")
        self.assertEqual(json.loads((state / "state.json").read_text())["rows"][0]["session_id"], "brew-smoke")

    def test_linux_setup_is_hooks_only_and_dry_run_does_not_change_config(self):
        root, _ = self.distribution()
        prefix, codex = self.folder / "linux", self.folder / "codex"
        args = parse_args(["--prefix", str(prefix), "--codex-home", str(codex), "--dry-run"])
        args.no_restart = True
        with contextlib.redirect_stdout(io.StringIO()):
            setup(args, root=root, platform="linux")
        self.assertFalse(prefix.exists())
        self.assertFalse(codex.exists())


if __name__ == "__main__":
    unittest.main()
