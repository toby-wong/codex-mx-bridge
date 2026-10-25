import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mxbridge.pets import DEFAULT_DISPLAY, configure, read_display, resolve_pet, validate_display

ROOT = Path(__file__).resolve().parent.parent


class PetRuleTests(unittest.TestCase):
    def test_short_names_and_scoped_rules_survive_cli_changes(self):
        rules = [
            {"location": "remote", "pet": "pingu"},
            {"location": "local", "client": "claude", "pet": "leader-avatar"},
            {"host": "very-long-remote-host-name", "client": "kiro", "pet": "clippit"},
            {"key": "remote/desktop/@client/claude/chat", "pet": "pingu/0123456789abcdef"},
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "display.json"
            path.write_text(json.dumps(dict(DEFAULT_DISPLAY, mode="pet", pet="clippit",
                pet_rules=rules, chat_view="recent", show_status=False)))
            result = subprocess.run([sys.executable, str(ROOT / "bridge.py"), "--state-dir", folder,
                "display", "--fps", "8"], capture_output=True, text=True, check=True)
            value = json.loads(result.stdout)
            self.assertEqual(value["pet_rules"], rules)
            self.assertEqual((value["pet"], value["fps"], value["show_status"], value["chat_view"]),
                             ("clippit", 8, False, "recent"))
            self.assertEqual(read_display(folder), value)
            self.assertFalse((Path(folder) / "state.json").exists())

    def test_bad_rule_selectors_are_rejected_without_overwriting_config(self):
        invalid = [
            None, {}, [None], [{}], [{"pet": "pingu"}],
            [{"pet": "pingu", "clinet": "claude"}],
            [{"pet": "pingu", "location": "somewhere"}],
            [{"pet": "pingu", "client": "unknown"}],
            [{"pet": "pingu", "key": ""}], [{"pet": "pingu", "key": "\n"}],
            [{"pet": "pingu", "host": 42}], [{"pet": "pingu", "host": None}],
            [{"pet": "pingu", "host": "x" * 256}], [{"pet": "pingu", "key": "x" * 701}],
            [{"pet": "pingu", "location": "local", "host": "desktop"}],
            [{"pet": "../pingu", "location": "remote"}],
            [{"pet": "pingu/../../outside", "client": "claude"}],
            [{"pet": "pingu", "location": "remote"}] * 65,
            [{"pet": f"pet-{n}", "key": str(n)} for n in range(16)],
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "display.json"
            for rules in invalid:
                raw = json.dumps(dict(DEFAULT_DISPLAY, mode="pet", pet="clippit", pet_rules=rules))
                path.write_text(raw)
                with self.subTest(rules=rules), self.assertRaises(ValueError):
                    configure(folder, fps=8)
                self.assertEqual(path.read_text(), raw)

    def test_rule_lists_are_independent_and_legacy_config_still_works(self):
        old = dict(DEFAULT_DISPLAY, mode="pet", pet="buddy/0123456789abcdef")
        old.pop("pet_rules")
        first, second = validate_display(old), validate_display(old)
        self.assertEqual(first["pet_rules"], [])
        first["pet_rules"].append({"location": "remote", "pet": "pingu"})
        self.assertEqual(second["pet_rules"], [])
        self.assertEqual(DEFAULT_DISPLAY["pet_rules"], [])
        rule = {"pet": "pingu", "client": "claude"}
        value = validate_display(dict(old, pet_rules=[rule]))
        rule["pet"] = "changed"
        self.assertEqual(value["pet_rules"][0]["pet"], "pingu")

    def test_aliases_ignore_incomplete_imports_and_reject_ambiguous_revisions(self):
        with tempfile.TemporaryDirectory() as folder:
            pets = Path(folder) / "pets"
            for revision in ("0123456789abcdef", ".import-in-progress"):
                path = pets / "pingu" / revision / "manifest.json"
                path.parent.mkdir(parents=True)
                path.write_text("{}")
            self.assertEqual(resolve_pet(folder, "pingu"), "pingu/0123456789abcdef")
            second = pets / "pingu" / "fedcba9876543210" / "manifest.json"
            second.parent.mkdir()
            second.write_text("{}")
            with self.assertRaisesRegex(ValueError, "several revisions"):
                resolve_pet(folder, "pingu")
            self.assertEqual(resolve_pet(folder, "pingu/0123456789abcdef"), "pingu/0123456789abcdef")
            for name in ("../pingu", "pingu/../../outside", "pingu/not-a-revision", "unknown"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    resolve_pet(folder, name)


if __name__ == "__main__":
    unittest.main()
