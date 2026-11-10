import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mxbridge.settings import Conflict, Settings
from mxbridge.themes import DEFAULT_THEME, validate_theme


class ThemeTests(unittest.TestCase):
    def test_defaults_and_custom_colors_preserve_future_fields(self):
        self.assertEqual(validate_theme({"schema_version": 1}), DEFAULT_THEME)
        value = {"schema_version": 1, "mode": "system", "palette": "custom",
                 "colors": {"light": {"accent": "#A1B2C3", "future": "keep"},
                            "future": {"keep": True}}}
        checked = validate_theme(value)
        self.assertEqual(checked["colors"]["light"]["accent"], "#a1b2c3")
        self.assertEqual(checked["colors"]["light"]["background"], "#f4f3ef")
        self.assertEqual(checked["colors"]["light"]["future"], "keep")
        self.assertEqual(checked["colors"]["future"], {"keep": True})
        checked["colors"]["dark"]["accent"] = "#123456"
        self.assertEqual(DEFAULT_THEME["colors"]["dark"]["accent"], "#a1ceb2")

    def test_invalid_modes_and_css_values_are_rejected(self):
        for value in ([], {}, {"schema_version": True}, {"schema_version": 2},
                      {"schema_version": 1, "mode": "auto"},
                      {"schema_version": 1, "palette": "unknown"},
                      {"schema_version": 1, "colors": []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_theme(value)
        for color in ("red", "#abc", "#12345678", "#000000; display:none", "url(https://example.com)", None, 42):
            with self.subTest(color=color), self.assertRaises(ValueError):
                validate_theme({"schema_version": 1, "colors": {"dark": {"background": color}}})

    def test_theme_save_is_separate_private_and_conflict_aware(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            display, bindings = root / "display.json", root / "herdr-focus.json"
            display.write_text('{"keep":"pet assignments"}')
            bindings.write_text('{"keep":"terminal bindings"}')
            settings = Settings(root)
            doc = settings.document("theme")[0]
            self.assertFalse((root / "theme.json").exists())
            value = {**doc["value"], "mode": "dark", "future": {"keep": True}}
            result = settings.save("theme", {"revision": doc["revision"], "value": value})
            self.assertEqual(result["document"]["value"], value)
            self.assertEqual((root / "theme.json").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(Conflict):
                settings.save("theme", {"revision": doc["revision"], "value": doc["value"]})
            prior = (root / "theme.json").read_bytes()
            updated = settings.save("theme", {"revision": result["document"]["revision"],
                                              "value": {**value, "palette": "slate"}})
            self.assertEqual(Path(updated["backup"]).read_bytes(), prior)
            invalid = copy.deepcopy(value)
            invalid["colors"]["dark"]["accent"] = "url(bad)"
            with self.assertRaises(ValueError):
                settings.save("theme", {"revision": updated["document"]["revision"], "value": invalid})
            self.assertEqual(settings.document("theme")[0]["value"]["palette"], "slate")
            self.assertEqual(display.read_text(), '{"keep":"pet assignments"}')
            self.assertEqual(bindings.read_text(), '{"keep":"terminal bindings"}')

    def test_default_path_and_invalid_file_recovery(self):
        with tempfile.TemporaryDirectory() as folder, patch("pathlib.Path.home", return_value=Path(folder)):
            settings = Settings(Path(folder) / ".local/state/codex-mx-bridge")
            doc = settings.document("theme")[0]
            path = Path(folder) / ".config/codex-mx-bridge/theme.json"
            self.assertEqual(Path(doc["path"]), path)
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version":1,"mode":"invalid"}')
            broken = settings.document("theme")[0]
            self.assertIsNone(broken["value"])
            self.assertIn("mode", broken["error"])
            result = settings.save("theme", {"revision": broken["revision"], "value": DEFAULT_THEME})
            self.assertEqual(json.loads(path.read_text()), DEFAULT_THEME)
            self.assertEqual(Path(result["backup"]).read_text(), '{"schema_version":1,"mode":"invalid"}')
