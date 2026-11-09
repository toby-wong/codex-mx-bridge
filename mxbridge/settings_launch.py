"""Start/reuse the settings server and make an optional Finder launcher."""
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import subprocess
import sys
import time
from urllib.parse import urlsplit
import webbrowser

from .settings import SettingsServer, WEB, bounded_read
from .state import atomic_json

ROOT = Path(__file__).resolve().parent.parent
RECORD = "settings-server.json"
APP_ID = "com.tobywo.codex-mx-bridge.settings"


def source_stamp():
    digest = hashlib.sha256(str(ROOT).encode())
    for path in sorted([*WEB.glob("*"), *Path(__file__).parent.glob("*.py")]):
        if path.is_file():
            digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()


def read_server(directory):
    try:
        value = json.loads(bounded_read(Path(directory) / RECORD, 8192))
        origin = urlsplit(value["origin"])
        if (origin.scheme != "http" or origin.hostname != "127.0.0.1" or
                origin.username is not None or origin.password is not None or
                origin.path or origin.query or origin.fragment or
                not origin.port or not 1 <= origin.port <= 65535 or
                not re.fullmatch(r"[A-Za-z0-9_-]{43}", value["token"]) or
                not re.fullmatch(r"[a-f0-9]{32}", value["instance"])):
            return None
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def request(record, path="/api/health", method="GET"):
    url = urlsplit(record["origin"])
    connection = http.client.HTTPConnection("127.0.0.1", url.port, timeout=1)
    try:
        connection.request(method, path, headers={
            "Authorization": "Bearer " + record["token"], "Origin": record["origin"]})
        response = connection.getresponse()
        raw = response.read(8193)
        if response.status != 200 or len(raw) > 8192:
            return None
        return json.loads(raw)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def live(record):
    health = request(record) if record else None
    return bool(health and health.get("app") == "codex-mx-settings" and
                health.get("instance") == record["instance"])


def install_app(command, destination=None):
    """Only replace bundles bearing our identity; never invoke a shell with user data."""
    destination = Path(destination or Path.home() / "Applications/Codex MX Bridge.app")
    plist = destination / "Contents/Info.plist"
    if destination.exists():
        try:
            existing = plistlib.loads(plist.read_bytes())
        except (OSError, ValueError) as exc:
            raise ValueError(f"Existing app is not a bridge launcher: {destination}") from exc
        if existing.get("CFBundleIdentifier") != APP_ID:
            raise ValueError(f"Existing app belongs to another application: {destination}")
    executable = destination / "Contents/MacOS/CodexMxSettings"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("#!/bin/sh\nexec " + shlex.join([str(p) for p in command]) + "\n")
    executable.chmod(0o700)
    plist.write_bytes(plistlib.dumps(dict(CFBundleIdentifier=APP_ID,
        CFBundleName="Codex MX Bridge", CFBundleDisplayName="Codex MX Bridge",
        CFBundleExecutable="CodexMxSettings", CFBundlePackageType="APPL",
        CFBundleVersion="1", LSUIElement=True, NSHighResolutionCapable=True)))
    return destination


def install_current_app(directory):
    """Stage immutable app code without changing trusted hooks or the plugin."""
    from scripts.install_local import stage_source
    prefix = (ROOT.parent.parent if ROOT.parent.name == "releases" else
              Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "codex-mx-bridge")
    prefix = prefix.expanduser().resolve()
    if prefix in {Path(prefix.anchor), Path.home().resolve(), ROOT.resolve()} or prefix in ROOT.resolve().parents:
        raise ValueError("Use a dedicated bridge data directory")
    prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
    release = stage_source(ROOT, prefix)
    command = [sys.executable, str(release / "bridge.py"), "--state-dir",
               str(Path(directory).absolute()), "settings"]
    launcher = prefix / "bin/codex-mx-settings"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\nexec " + shlex.join(command) + ' "$@"\n')
    launcher.chmod(0o700)
    app = install_app([str(launcher)])
    atomic_json(prefix / "settings-app.json", dict(release=str(release), python=sys.executable,
        launcher=str(launcher), app=str(app), state_dir=str(Path(directory).absolute())))
    return app, command


@contextmanager
def launch_lock(directory):
    import fcntl
    path = Path(directory) / "settings-server.lock"
    with path.open("a+b") as stream:
        os.fchmod(stream.fileno(), 0o600)
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("Another settings launcher is busy; try again")
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def serve(directory, *, port=0, open_browser=True):
    directory = Path(directory)
    with SettingsServer(directory, port) as server:
        record = dict(origin=server.origin, token=server.token, instance=server.instance,
                      pid=os.getpid(), source=source_stamp())
        atomic_json(directory / RECORD, record)
        print(f"Settings app listening at {server.origin}", flush=True)
        if open_browser:
            webbrowser.open(server.url)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
        finally:
            current = read_server(directory)
            if current and current["instance"] == server.instance:
                (directory / RECORD).unlink(missing_ok=True)


def launch(directory, *, port=0, open_browser=True, stop=False):
    directory = Path(directory).expanduser().absolute()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with launch_lock(directory):
        record = read_server(directory)
        running = live(record)
        if stop:
            if running:
                request(record, "/api/shutdown", "POST")
            print("Settings app stopped." if running else "Settings app is not running.")
            return 0
        stamp = source_stamp()
        if running and (record.get("source") != stamp or port and urlsplit(record["origin"]).port != port):
            if not request(record, "/api/shutdown", "POST"):
                raise ValueError("Cannot stop the older settings app")
            deadline = time.monotonic() + 4
            while live(record):
                if time.monotonic() >= deadline:
                    raise ValueError("The older settings app is still stopping; try again")
                time.sleep(0.1)
            running = False
        if not running:
            command = [sys.executable, str(ROOT / "bridge.py"), "--state-dir", str(directory),
                       "settings", "--foreground", "--no-open", "--port", str(port)]
            log = directory / "settings-server.log"
            with log.open("ab") as stream:
                os.fchmod(stream.fileno(), 0o600)
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream,
                                         stderr=stream, start_new_session=True)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                record = read_server(directory)
                if record and record.get("pid") == child.pid and live(record):
                    break
                if child.poll() is not None:
                    raise ValueError(f"Settings app could not start; see {log}")
                time.sleep(0.1)
            else:
                child.terminate()
                raise ValueError(f"Settings app did not become ready; see {log}")
        url = record["origin"] + "/#" + record["token"]
        if open_browser:
            webbrowser.open(url)
        else:
            print(url)
        return 0
