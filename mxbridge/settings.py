"""On-demand, authenticated loopback UI for bridge settings and pet imports."""
import base64
import binascii
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import struct
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import zipfile

from . import __version__, focus, pet_download, pets
from .state import FINAL, empty
from .themes import DEFAULT_THEME, validate_theme

WEB = Path(__file__).with_name("settings_web")
MAX_UPLOAD = 20 * 1024 * 1024
MAX_BODY = 28 * 1024 * 1024
FRAME_NAME = re.compile(r"[a-z_]{1,32}-[0-9]{1,2}\.png")
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/model.mjs": ("model.mjs", "text/javascript; charset=utf-8"),
    "/theme.mjs": ("theme.mjs", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}


class Conflict(ValueError):
    pass


def bounded_read(path, limit):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{Path(path).name} exceeds its size limit")
    return raw


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def private_write(path, raw):
    with Path(path).open("xb") as stream:
        if os.name == "posix":
            os.fchmod(stream.fileno(), 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def catalog_names():
    path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "session_index.jsonl"
    result = {}
    try:
        raw = bounded_read(path, 4 * 1024 * 1024).decode("utf-8")
    except (OSError, ValueError):
        return result
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
            key, name = entry.get("id"), entry.get("thread_name")
            if isinstance(key, str) and isinstance(name, str):
                name = "".join(c for c in name if c.isprintable())[:80].strip()
                if name:
                    result[key] = name
                else:
                    result.pop(key, None)
        except (ValueError, AttributeError):
            continue
    return result


class Settings:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().absolute()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def document(self, kind):
        if kind == "display":
            path = pets.display_path(self.directory)
            read = pets.display_path(self.directory, for_read=True)
            default = pets.DEFAULT_DISPLAY
            validate = pets.validate_display
        elif kind == "bindings":
            path = read = self.directory / focus.CONFIG
            default = {"schema_version": 1, "bindings": [], "remote_bindings": []}
            validate = focus.validate_bindings
        elif kind == "theme":
            path = read = pets.display_path(self.directory).with_name("theme.json")
            default = DEFAULT_THEME
            validate = validate_theme
        else:
            raise ValueError("Unknown settings document")
        try:
            raw = bounded_read(read, pets.MAX_DISPLAY_BYTES)
        except FileNotFoundError:
            raw = None
        revision = hashlib.sha256(str(read).encode() + b"\0" +
                                  (b"missing" if raw is None else raw)).hexdigest()
        error, value = "", None
        try:
            original = default if raw is None else json.loads(raw)
            # Preserve future/unknown fields when editing supported settings.
            value = {**original, **validate(original)}
        except (ValueError, TypeError) as exc:
            error = str(exc)
        return dict(value=value, revision=revision, error=error, path=str(path),
                    read_path=str(read)), raw

    def save(self, kind, payload):
        if not isinstance(payload, dict) or set(payload) != {"revision", "value"}:
            raise ValueError("Save needs the loaded revision and complete settings")
        value = self.validate(kind, payload["value"])
        raw = encode(value)
        with self.lock:
            current, before = self.document(kind)
            if payload["revision"] != current["revision"]:
                raise Conflict("Settings changed elsewhere. Reload the file before saving.")
            if value == current["value"]:
                return dict(document=current, backup=None)
            path = Path(current["path"])
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            backup = None
            if before is not None:
                backup = path.with_name(path.name + f".settings-backup-{time.time_ns()}")
                private_write(backup, before)
            if self.document(kind)[0]["revision"] != current["revision"]:
                raise Conflict("Settings changed while saving. Reload the file before saving.")
            fd, temporary = tempfile.mkstemp(prefix=".mx-settings-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return dict(document=self.document(kind)[0], backup=str(backup) if backup else None)

    @staticmethod
    def validate(kind, value):
        if not isinstance(value, dict):
            raise ValueError("Settings must be a JSON object")
        validators = {"display": pets.validate_display, "bindings": focus.validate_bindings,
                      "theme": validate_theme}
        if kind not in validators:
            raise ValueError("Unknown settings document")
        checked = validators[kind](value)
        value = {**value, **checked}
        if len(encode(value)) > pets.MAX_DISPLAY_BYTES:
            raise ValueError("Settings exceed 64 KiB")
        return value

    def pack(self, pet_id):
        if not isinstance(pet_id, str) or not pets.PET_ID.fullmatch(pet_id):
            raise ValueError("Use an imported pet revision ID")
        root = (self.directory / "pets").resolve()
        folder = (root / pet_id).resolve()
        if not folder.is_relative_to(root) or folder == root:
            raise ValueError("Pet path is outside the library")
        manifest_path = (folder / "manifest.json").resolve()
        if not manifest_path.is_relative_to(folder):
            raise ValueError("Pet manifest is outside its pack")
        value = json.loads(bounded_read(manifest_path, 65536))
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("Unsupported pet manifest")
        width, height = value.get("frame_width"), value.get("frame_height")
        animations = value.get("animations")
        if (any(type(v) is not int or not 1 <= v <= 512 for v in (width, height)) or
                not isinstance(animations, dict) or not pets.REQUIRED.issubset(animations) or
                len(animations) > 16):
            raise ValueError("Invalid pet geometry or animation list")
        count = 0
        for name, files in animations.items():
            if (not re.fullmatch(r"[a-z_]{1,32}", name) or
                    not isinstance(files, list) or not 1 <= len(files) <= 32 or
                    any(not isinstance(f, str) or not FRAME_NAME.fullmatch(f) for f in files)):
                raise ValueError("Invalid pet animation frames")
            count += len(files)
        if count > 128:
            raise ValueError("Pet exceeds 128 frames")
        return folder, dict(id=pet_id, name=pet_id.split("/")[0], width=width, height=height,
                            animations=animations, error="")

    def library(self):
        result = []
        for pet_id in pets.list_pets(self.directory)[:256]:
            try:
                result.append(self.pack(pet_id)[1])
            except (OSError, ValueError) as exc:
                result.append(dict(id=pet_id, name=pet_id.split("/")[0], animations={}, error=str(exc)))
        return result

    def frame(self, pet_id, filename):
        folder, pack = self.pack(pet_id)
        if filename not in {f for frames in pack["animations"].values() for f in frames}:
            raise ValueError("Frame is not part of this pet")
        path = (folder / filename).resolve()
        if not path.is_relative_to(folder):
            raise ValueError("Frame is outside its pack")
        raw = bounded_read(path, 2 * 1024 * 1024)
        if (len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR" or
                struct.unpack(">II", raw[16:24]) != (pack["width"], pack["height"])):
            raise ValueError("Invalid imported PNG frame")
        return raw

    def import_pack(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"name", "filename", "data", "layout"}:
            raise ValueError("Invalid pet upload")
        name, filename, encoded = (payload.get(k) for k in ("name", "filename", "data"))
        self.validate_pet_name(name)
        if not isinstance(filename, str) or len(filename) > 255 or not isinstance(encoded, str):
            raise ValueError("Select a PNG, WebP or pet ZIP file")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid uploaded file encoding") from exc
        return self.import_bytes(name, filename, raw, payload.get("layout"))

    @staticmethod
    def validate_pet_name(name):
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", name):
            raise ValueError("Name your pet with 1–48 letters, numbers, underscores or hyphens")

    def import_url(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"name", "url", "layout"}:
            raise ValueError("Invalid pet URL import")
        self.validate_pet_name(payload.get("name"))
        pets.pillow()
        raw, filename = pet_download.fetch_pet(payload.get("url"))
        return self.import_bytes(payload["name"], filename, raw, payload.get("layout"))

    def import_bytes(self, name, filename, raw, custom_layout):
        if not 0 < len(raw) <= MAX_UPLOAD:
            raise ValueError("Pet uploads must be at most 20 MiB")
        suffix = Path(filename).suffix.lower()
        sheet = raw
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    entries = archive.infolist()
                    if (len(entries) > 128 or sum(e.file_size for e in entries) > MAX_UPLOAD + 65536 or
                            any(e.flag_bits & 1 or "\\" in e.filename or
                                PurePosixPath(e.filename).is_absolute() or
                                ".." in PurePosixPath(e.filename).parts or
                                (e.external_attr >> 16) & 0o170000 == 0o120000 for e in entries)):
                        raise ValueError("Use a small pet package without encrypted files or unsafe paths")
                    sheets = [e for e in entries if PurePosixPath(e.filename).name in
                              {"spritesheet.webp", "spritesheet.png"} and not e.is_dir()]
                    if len(sheets) != 1 or not 0 < sheets[0].file_size <= MAX_UPLOAD:
                        raise ValueError("Pet ZIP needs exactly one spritesheet.png or spritesheet.webp")
                    with archive.open(sheets[0]) as stream:
                        sheet = stream.read(MAX_UPLOAD + 1)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                raise ValueError("Cannot read this pet ZIP package") from exc
        elif suffix not in {".png", ".webp"}:
            raise ValueError("Choose a .codex-pet.zip, PNG or WebP file")
        with self.lock, tempfile.TemporaryDirectory(prefix="mx-settings-pet-") as folder:
            path = Path(folder) / "sheet"
            path.write_bytes(sheet)
            layout_path = None
            if custom_layout is not None:
                layout = encode(custom_layout)
                if len(layout) > 65536:
                    raise ValueError("Custom layout exceeds 64 KiB")
                layout_path = Path(folder) / "layout.json"
                layout_path.write_bytes(layout)
            Image = pets.pillow()
            try:
                pet_id = pets.import_pet(self.directory, path, name, layout_path)
            except Image.DecompressionBombError as exc:
                raise ValueError("Use a static PNG/WebP atlas up to 4096×4096 pixels") from exc
        return dict(pet=pet_id, pets=self.library())

    def activity(self):
        error = ""
        try:
            value = json.loads(bounded_read(self.directory / "state.json", 16 * 1024 * 1024))
            if (not isinstance(value, dict) or value.get("schema_version") != 1 or
                    not isinstance(value.get("rows"), list) or not isinstance(value.get("remotes"), dict)):
                raise ValueError("Invalid bridge state")
        except FileNotFoundError:
            value = empty()
        except (OSError, ValueError) as exc:
            error, value = str(exc), empty()
        names = catalog_names()
        now, chats, sources = time.time(), [], []
        groups = [("local", True, dict(rows=value["rows"], received_at=None, error=""))]
        groups += [(host, False, remote) for host, remote in sorted(value["remotes"].items())]
        for host, local, remote in groups:
            if not isinstance(remote, dict) or not isinstance(remote.get("rows"), list):
                continue
            received = remote.get("received_at", 0)
            offline = not local and (bool(remote.get("error")) or not isinstance(received, (int, float)) or
                                     now > received + 15)
            sources.append(dict(host=host, location="local" if local else "remote",
                                count=len(remote["rows"]), offline=offline, received_at=received,
                                error=str(remote.get("error", ""))[:300]))
            for row in remote["rows"][:256]:
                if not isinstance(row, dict) or not isinstance(row.get("key"), str):
                    continue
                status = row.get("status", "READY")
                expiry = row.get("valid_until", 0)
                if offline:
                    status = "OFFLINE"
                elif status not in FINAL and isinstance(expiry, (int, float)) and now > expiry:
                    status = "STALE"
                client = row.get("client", "codex")
                saved = names.get(row.get("session_id", ""), "") if local and client == "codex" else ""
                chats.append(dict(key=row["key"] if local else f"remote/{host}/{row['key']}",
                    name=str(row.get("name", client))[:80], fallback_name=str(row.get("fallback_name", ""))[:80],
                    saved_name=saved, client=client, kind=row.get("kind", "session"), host=host,
                    location="local" if local else "remote", status=status, raw_status=row.get("status", "READY"),
                    updated_at=row.get("updated_at", 0), created_at=row.get("created_at"),
                    order=row.get("order", 0)))
        return dict(chats=chats, sources=sources, state_error=error, dropped_rows=value.get("dropped_rows", 0))

    def snapshot(self):
        result = dict(version=__version__, config=self.document("display")[0],
                      bindings=self.document("bindings")[0], theme=self.document("theme")[0],
                      pets=self.library(), **self.activity())
        result["diagnostics"] = []
        for name in ("display-status.txt", "render-status.txt", "focus-status.txt", "hook-error.txt",
                     "hook-claude-error.txt", "hook-kiro-error.txt", "hook-pi-error.txt"):
            path = self.directory / name
            try:
                text = bounded_read(path, 65536).decode("utf-8", errors="replace")
                result["diagnostics"].append(dict(name=name, text=text, updated_at=path.stat().st_mtime))
            except (OSError, ValueError):
                pass
        try:
            pets.pillow()
            result["can_import"] = True
        except ValueError:
            result["can_import"] = False
        return result


class SettingsServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, directory, port=0):
        self.settings = Settings(directory)
        self.token = secrets.token_urlsafe(32)
        self.instance = secrets.token_hex(16)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.url = f"{self.origin}/#{self.token}"

    def server_bind(self):
        # This loopback app must not wait for reverse DNS during startup.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    server_version = "CodexMXSettings"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_args):
        pass

    def reply(self, status, body, content_type="application/json; charset=utf-8"):
        raw = body if isinstance(body, bytes) else encode(body)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' blob:; connect-src 'self'; "
                         "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def allowed(self, authenticated=False):
        if self.headers.get("Host") != urlsplit(self.server.origin).netloc:
            self.reply(403, dict(error="Unrecognized host"))
            return False
        origin = self.headers.get("Origin")
        if (origin is not None and origin != self.server.origin) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.reply(403, dict(error="Only the local settings app may access this endpoint"))
            return False
        if authenticated and not secrets.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + self.server.token):
            self.reply(401, dict(error="Open Settings again from the bridge launcher to reconnect"))
            return False
        return True

    def do_GET(self):
        try:
            route = urlsplit(self.path)
            if not self.allowed(authenticated=route.path.startswith("/api/")):
                return
            if route.path in STATIC:
                name, content_type = STATIC[route.path]
                self.reply(200, (WEB / name).read_bytes(), content_type)
            elif route.path == "/api/health":
                self.reply(200, dict(app="codex-mx-settings", instance=self.server.instance))
            elif route.path == "/api/state":
                self.reply(200, self.server.settings.snapshot())
            elif route.path == "/api/frame":
                query = parse_qs(route.query)
                self.reply(200, self.server.settings.frame(query.get("pet", [""])[0],
                           query.get("file", [""])[0]), "image/png")
            else:
                self.reply(404, dict(error="Not found"))
        except (OSError, ValueError) as exc:
            self.reply(400, dict(error=str(exc)))

    def do_POST(self):
        try:
            if not self.allowed(authenticated=True):
                return
            route = urlsplit(self.path).path
            if route == "/api/shutdown":
                self.reply(200, dict(stopped=True))
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if route not in {"/api/display", "/api/display/validate", "/api/bindings", "/api/theme",
                             "/api/pets/import", "/api/pets/import-url"}:
                self.reply(404, dict(error="Not found"))
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.reply(415, dict(error="Send JSON"))
                return
            limit = MAX_BODY if route == "/api/pets/import" else 2 * pets.MAX_DISPLAY_BYTES
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Transfer-Encoding") or not 0 < length <= limit:
                self.reply(413, dict(error="Request is empty or too large"))
                return
            payload = json.loads(self.rfile.read(length))
            if route == "/api/pets/import":
                result = self.server.settings.import_pack(payload)
            elif route == "/api/pets/import-url":
                result = self.server.settings.import_url(payload)
            elif route == "/api/display/validate":
                result = dict(value=self.server.settings.validate("display", payload))
            else:
                result = self.server.settings.save(route.removeprefix("/api/"), payload)
            self.reply(200, result)
        except Conflict as exc:
            self.reply(409, dict(error=str(exc)))
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            self.reply(400, dict(error=str(exc)))

    def do_OPTIONS(self):
        self.reply(403, dict(error="Cross-origin access is not enabled"))
