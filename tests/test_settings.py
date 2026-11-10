import base64
import http.client
import io
import json
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
import zlib

from mxbridge.pets import DEFAULT_DISPLAY, STANDARD, configure
from mxbridge.settings import Conflict, Settings, SettingsServer
from mxbridge.settings_launch import APP_ID, install_app, install_current_app, read_server
from mxbridge.state import atomic_json, empty

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

ROOT = Path(__file__).resolve().parent.parent


def fixture_sheet():
    image = Image.new("RGBA", (1536, 1872))
    draw = ImageDraw.Draw(image)
    for row, count in STANDARD.values():
        for index in range(count):
            draw.rectangle((index * 192 + 50, row * 208 + 30,
                            index * 192 + 140, row * 208 + 180), fill=(57, 125, 90, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root)

    def save(self, value, kind="display"):
        doc = self.settings.document(kind)[0]
        return self.settings.save(kind, dict(revision=doc["revision"], value=value))

    def test_preserves_unknown_fields_and_keeps_a_private_backup(self):
        before = dict(DEFAULT_DISPLAY, future_setting={"keep": True}, pet_rules=[
            dict(client="pi", location="remote", pet="apupepe"),
            dict(client="pi", location="local", pet="banana-cat")])
        raw = json.dumps(before).encode()
        (self.root / "display.json").write_bytes(raw)
        atomic_json(self.root / "state.json", empty())
        state_before = (self.root / "state.json").read_bytes()
        doc = self.settings.document("display")[0]
        doc["value"]["fps"] = 8
        result = self.settings.save("display", dict(revision=doc["revision"], value=doc["value"]))
        saved = json.loads((self.root / "display.json").read_text())
        self.assertEqual(saved, dict(before, fps=8))
        self.assertEqual(Path(result["backup"]).read_bytes(), raw)
        self.assertEqual((self.root / "state.json").read_bytes(), state_before)
        if os.name == "posix":
            for path in (self.root / "display.json", Path(result["backup"])):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_file_edit_and_two_browser_saves_reject_stale_revisions(self):
        configure(self.root, fps=4)
        first = self.settings.document("display")[0]
        second = self.settings.document("display")[0]
        self.settings.save("display", dict(revision=first["revision"], value=dict(first["value"], fps=5)))
        with self.assertRaises(Conflict):
            self.settings.save("display", dict(revision=second["revision"], value=dict(second["value"], fps=6)))
        current = self.settings.document("display")[0]
        configure(self.root, fps=7)
        with self.assertRaises(Conflict):
            self.settings.save("display", dict(revision=current["revision"], value=dict(current["value"], fps=8)))
        self.assertEqual(self.settings.document("display")[0]["value"]["fps"], 7)

    def test_bad_values_and_nonfinite_unknown_fields_keep_existing_bytes(self):
        configure(self.root, fps=8)
        path = self.root / "display.json"
        before = path.read_bytes()
        for changes in (dict(fps=90), dict(pet="../bad"), dict(show_status="off"),
                        dict(name_overrides={"chat": "x" * 81}), dict(future=float("nan")),
                        dict(pet_rules=[dict(client="pi", location="local", host="desktop", pet="buddy")])):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.save(dict(DEFAULT_DISPLAY, **changes))
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_file_is_readable_for_recovery_and_backed_up_on_save(self):
        path = self.root / "display.json"
        path.write_text("not valid json")
        document = self.settings.document("display")[0]
        self.assertIsNone(document["value"])
        self.assertTrue(document["error"])
        saved = self.save(dict(DEFAULT_DISPLAY, fps=7))
        self.assertEqual(Path(saved["backup"]).read_text(), "not valid json")
        self.assertEqual(saved["document"]["value"]["fps"], 7)

    def test_default_location_migrates_legacy_without_touching_it(self):
        with patch("pathlib.Path.home", return_value=self.root):
            state = self.root / ".local/state/codex-mx-bridge"
            state.mkdir(parents=True)
            legacy = state / "display.json"
            legacy.write_text(json.dumps(dict(DEFAULT_DISPLAY, fps=8)))
            settings = Settings(state)
            document = settings.document("display")[0]
            self.assertEqual(document["value"]["fps"], 8)
            value = dict(document["value"], show_name=False)
            result = settings.save("display", dict(revision=document["revision"], value=value))
            self.assertEqual(result["document"]["path"], str(self.root / ".config/codex-mx-bridge/display.json"))
            self.assertEqual(json.loads(legacy.read_text())["show_name"], True)

    def test_local_remote_bindings_are_validated_and_backed_up(self):
        uid = "12345678-1234-1234-1234-123456789abc"
        value = dict(schema_version=1, bindings=[dict(socket_path="/tmp/herdr.sock", iterm_id=uid)],
                     remote_bindings=[dict(source="desk", ssh_target="desk-ssh", herdr_path="/usr/bin/herdr",
                                           remote_session="work", iterm_id=uid)])
        self.save(value, "bindings")
        before = (self.root / "herdr-focus.json").read_bytes()
        for invalid in (dict(value, bindings=value["bindings"] * 2),
                        dict(value, remote_bindings=[dict(value["remote_bindings"][0], ssh_target="-oProxyCommand=bad")])):
            with self.assertRaises(ValueError):
                self.save(invalid, "bindings")
        self.assertEqual((self.root / "herdr-focus.json").read_bytes(), before)
        result = self.save(dict(value, bindings=[]), "bindings")
        self.assertEqual(Path(result["backup"]).read_bytes(), before)
        self.assertEqual(result["document"]["value"]["remote_bindings"], value["remote_bindings"])

    def test_activity_exposes_only_display_metadata_and_stable_remote_keys(self):
        state = empty()
        state["rows"] = [dict(key="@client/pi/local", session_id="pi", name="Pi", client="pi",
                              kind="subagent", iterm_id="private", tty="private", herdr_socket="private",
                              session_path="private", status="WORKING", valid_until=1)]
        state["remotes"] = {"desk": dict(rows=[dict(key="@client/pi/child", name="Child", client="pi",
            status="CLOSED", valid_until=1)], error="offline", received_at=1)}
        atomic_json(self.root / "state.json", state)
        with patch("mxbridge.settings.catalog_names", return_value={}):
            result = self.settings.activity()
        self.assertEqual([r["key"] for r in result["chats"]], ["@client/pi/local", "remote/desk/@client/pi/child"])
        self.assertEqual([r["status"] for r in result["chats"]], ["STALE", "OFFLINE"])
        self.assertEqual(result["chats"][1]["raw_status"], "CLOSED")
        self.assertNotIn("private", json.dumps(result))

    def test_manifest_and_frame_paths_cannot_escape_library(self):
        folder = self.root / "pets/buddy/0123456789abcdef"
        folder.mkdir(parents=True)
        value = dict(schema_version=1, frame_width=1, frame_height=1,
                     animations={name: [name + "-0.png"] for name in ["idle", "running", "waiting", "review", "failed"]})
        atomic_json(folder / "manifest.json", value)
        outside = self.root / "private.png"
        outside.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + struct.pack(">II", 1, 1))
        if os.name == "posix":
            (folder / "idle-0.png").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "outside"):
                self.settings.frame("buddy/0123456789abcdef", "idle-0.png")
        for filename in ("../../private.png", "other-0.png"):
            with self.assertRaises(ValueError):
                self.settings.frame("buddy/0123456789abcdef", filename)
        with self.assertRaises(ValueError):
            self.settings.pack("../private")
        value["animations"]["idle"] = ["../../private.png"]
        atomic_json(folder / "manifest.json", value)
        self.assertTrue(self.settings.library()[0]["error"])

    @unittest.skipIf(Image is None, "Pillow optional extra needed")
    def test_atlas_and_zip_import_preserve_selection_and_reuse_revision(self):
        configure(self.root, fps=8)
        before = (self.root / "display.json").read_bytes()
        sheet = fixture_sheet()
        direct = dict(name="buddy", filename="buddy.png", data=base64.b64encode(sheet).decode())
        pet = self.settings.import_pack(direct)["pet"]
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("pet.json", '{"id":"buddy"}')
            zipped.writestr("spritesheet.png", sheet)
        result = self.settings.import_pack(dict(name="buddy", filename="buddy.codex-pet.zip",
            data=base64.b64encode(archive.getvalue()).decode()))
        self.assertEqual(result["pet"], pet)
        self.assertEqual(len(result["pets"]), 1)
        self.assertEqual(sum(len(a) for a in result["pets"][0]["animations"].values()), 57)
        self.assertTrue(self.settings.frame(pet, "idle-0.png").startswith(b"\x89PNG"))
        self.assertEqual((self.root / "display.json").read_bytes(), before)

    @unittest.skipIf(Image is None, "Pillow optional extra needed")
    def test_url_package_import_preserves_config_and_existing_revision(self):
        configure(self.root, fps=8)
        before = (self.root / "display.json").read_bytes()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("spritesheet.png", fixture_sheet())
        metadata = json.dumps({"pet": {"downloadUrl": "/api/pets/buddy/download?v=123"}}).encode()
        payload = dict(name="buddy", url="https://codex-pets.net/#/pets/buddy")
        with patch("mxbridge.pet_download.download", side_effect=[metadata, archive.getvalue()] * 2):
            first = self.settings.import_url(payload)
            second = self.settings.import_url(payload)
        self.assertEqual(first["pet"], second["pet"])
        self.assertEqual(len(second["pets"]), 1)
        self.assertEqual((self.root / "display.json").read_bytes(), before)
        with patch("mxbridge.pet_download.fetch_pet") as fetch:
            with self.assertRaises(ValueError):
                self.settings.import_url(dict(payload, name="../outside"))
            fetch.assert_not_called()

    @unittest.skipIf(Image is None, "Pillow optional extra needed")
    def test_url_import_reports_oversized_image_dimensions_without_creating_a_pet(self):
        def chunk(kind, content):
            return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
        png = (b"\x89PNG\r\n\x1a\n" +
               chunk(b"IHDR", struct.pack(">IIBBBBB", 20000, 20000, 8, 6, 0, 0, 0)) +
               chunk(b"IDAT", zlib.compress(b"\0")) + chunk(b"IEND", b""))
        with patch("mxbridge.pet_download.fetch_pet", return_value=(png, "pet.png")):
            with self.assertRaisesRegex(ValueError, "4096"):
                self.settings.import_url(dict(name="too-big", url="https://assets.example/pet.png"))
        self.assertFalse((self.root / "pets").exists())
        self.assertFalse((self.root / "display.json").exists())

    def test_zip_unsafe_paths_ambiguous_atlases_and_expansion_are_rejected(self):
        for entries in ([("../spritesheet.webp", b"bad")], [("spritesheet.webp", b"bad"), ("spritesheet.png", b"bad")],
                        [("spritesheet.webp", b"bad"), ("large", b"\0" * (21 * 1024 * 1024))]):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in entries:
                    archive.writestr(name, content)
            with self.subTest(entries=[n for n, _ in entries]), self.assertRaises(ValueError):
                self.settings.import_pack(dict(name="buddy", filename="buddy.zip",
                    data=base64.b64encode(output.getvalue()).decode()))
        self.assertFalse((self.root / "pets").exists())


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = SettingsServer(self.temp.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path="/api/state", *, method="GET", value=None, authorized=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = {"Authorization": "Bearer " + self.server.token} if authorized else {}
        if headers:
            request_headers.update(headers)
        body = json.dumps(value) if value is not None else None
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_static_shell_has_no_private_data_and_api_requires_launch_token(self):
        (Path(self.temp.name) / "display.json").write_text(json.dumps(dict(DEFAULT_DISPLAY, pet="secret-pet")))
        status, headers, raw = self.request("/", authorized=False)
        self.assertEqual(status, 200)
        self.assertNotIn(b"secret-pet", raw)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request(authorized=False)[0], 401)
        self.assertEqual(self.request(headers={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(self.request()[0], 200)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_foreign_host_origin_and_cross_site_requests_are_rejected_even_with_token(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
                        {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request(headers=headers)[0], 403)
            self.assertEqual(self.request("/api/display", method="POST", value={}, headers=headers)[0], 403)
        self.assertEqual(self.request("/", method="OPTIONS", authorized=False)[0], 403)

    def test_http_save_and_conflict_preserve_file(self):
        doc = json.loads(self.request()[2])["config"]
        payload = dict(revision=doc["revision"], value=dict(doc["value"], fps=8))
        self.assertEqual(self.request("/api/display", method="POST", value=payload)[0], 200)
        payload["value"]["fps"] = 3
        self.assertEqual(self.request("/api/display", method="POST", value=payload)[0], 409)
        saved = json.loads((Path(self.temp.name) / "display.json").read_text())
        self.assertEqual(saved["fps"], 8)

    def test_bad_content_oversize_body_and_unlisted_paths_are_rejected(self):
        self.assertEqual(self.request("/api/display", method="POST", value={},
            headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/display", method="POST",
            headers={"Content-Type": "application/json", "Content-Length": "999999999"})[0], 413)
        self.assertEqual(self.request("/../state.json")[0], 404)
        self.assertEqual(self.request("/api/frame?pet=../private&file=secret")[0], 400)
        self.assertFalse((Path(self.temp.name) / "display.json").exists())

    @unittest.skipIf(Image is None, "Pillow optional extra needed")
    def test_url_import_is_authenticated_and_uses_the_existing_importer(self):
        payload = dict(name="url-pet", url="https://assets.example/pet.png")
        with patch("mxbridge.pet_download.fetch_pet", return_value=(fixture_sheet(), "pet.png")) as fetch:
            self.assertEqual(self.request("/api/pets/import-url", method="POST", value=payload, authorized=False)[0], 401)
            fetch.assert_not_called()
            status, _, raw = self.request("/api/pets/import-url", method="POST", value=payload)
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)["pet"].startswith("url-pet/"))
            fetch.assert_called_once_with(payload["url"])
        self.assertFalse((Path(self.temp.name) / "display.json").exists())


class LauncherTests(unittest.TestCase):
    def test_loopback_server_starts_without_hostname_resolution(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch("socket.getfqdn", side_effect=OSError("DNS unavailable")):
            with SettingsServer(folder) as server:
                self.assertEqual(server.server_name, "127.0.0.1")
                self.assertGreater(server.server_port, 0)
                self.assertEqual(server.origin, f"http://127.0.0.1:{server.server_port}")

    def test_app_only_install_stages_code_without_rewriting_the_existing_bridge(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            source = Path(folder) / "checkout"
            source.mkdir()
            (source / "bridge.py").write_text("# fixture bridge")
            (source / "mxbridge/settings_web").mkdir(parents=True)
            (source / "mxbridge/settings_web/index.html").write_text("<title>Settings</title>")
            prefix = home / ".local/share/codex-mx-bridge"
            (prefix / "bin").mkdir(parents=True)
            launcher = prefix / "bin/codex-mx"
            launcher.write_text("keep existing launcher")
            manifest = prefix / "installation.json"
            manifest.write_text('{"release":"original","plugin_release":"original"}')
            hooks = home / ".codex/hooks.json"
            hooks.parent.mkdir()
            hooks.write_text('{"keep":"trusted hooks"}')
            with patch("pathlib.Path.home", return_value=home), patch("mxbridge.settings_launch.ROOT", source), \
                    patch.dict(os.environ, {"XDG_DATA_HOME": str(home / ".local/share")}):
                app, command = install_current_app(home / "state")
            self.assertTrue((app / "Contents/Info.plist").is_file())
            self.assertEqual(launcher.read_text(), "keep existing launcher")
            self.assertEqual(manifest.read_text(), '{"release":"original","plugin_release":"original"}')
            self.assertEqual(hooks.read_text(), '{"keep":"trusted hooks"}')
            record = json.loads((prefix / "settings-app.json").read_text())
            self.assertEqual(command[1], str(Path(record["release"]) / "bridge.py"))
            self.assertTrue((Path(record["release"]) / "mxbridge/settings_web/index.html").is_file())
            self.assertEqual((prefix / "bin/codex-mx-settings").stat().st_mode & 0o777, 0o700)

    def test_app_quotes_paths_and_refuses_an_unrelated_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / "Applications/Bridge App.app"
            install_app(["/Users/a b/bridge", "settings", "--state-dir", "/tmp/a;$(touch nope)"], app)
            plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            self.assertEqual(plist["CFBundleIdentifier"], APP_ID)
            script = (app / "Contents/MacOS/CodexMxSettings").read_text()
            self.assertIn("'/Users/a b/bridge'", script)
            self.assertIn("'/tmp/a;$(touch nope)'", script)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps(dict(CFBundleIdentifier="another.app")))
            with self.assertRaises(ValueError):
                install_app(["other"], app)

    def test_untrusted_runtime_record_cannot_redirect_token_off_machine(self):
        with tempfile.TemporaryDirectory() as folder:
            value = dict(origin="https://remote.example:444", token="a" * 43, instance="b" * 32)
            atomic_json(Path(folder) / "settings-server.json", value)
            self.assertIsNone(read_server(folder))
            value["origin"] = "http://127.0.0.1:12345"
            atomic_json(Path(folder) / "settings-server.json", value)
            self.assertEqual(read_server(folder), value)

    def test_cli_starts_reuses_and_stops_one_private_server(self):
        if os.name != "posix":
            self.skipTest("Settings launcher supports macOS/Linux")
        with tempfile.TemporaryDirectory() as folder:
            command = [sys.executable, str(ROOT / "bridge.py"), "--state-dir", folder, "settings"]
            try:
                first = subprocess.run([*command, "--no-open"], text=True, capture_output=True, timeout=15)
                log = Path(folder) / "settings-server.log"
                self.assertEqual(first.returncode, 0,
                    first.stderr + (log.read_text() if log.exists() else ""))
                record = read_server(folder)
                second = subprocess.run([*command, "--no-open"], text=True, capture_output=True, timeout=15)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(first.stdout, second.stdout)
                self.assertEqual(read_server(folder)["pid"], record["pid"])
                self.assertEqual((Path(folder) / "settings-server.json").stat().st_mode & 0o777, 0o600)
            finally:
                subprocess.run([*command, "--stop"], capture_output=True, timeout=15)


if __name__ == "__main__":
    unittest.main()
