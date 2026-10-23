"""Bounded OpenSSH polling; credentials and host trust stay with OpenSSH."""
import json
import math
import re
import shlex
import subprocess
import time
from .state import FINAL, MAX_ROWS, clean


def command(host, script, python="python3.15", remote_state=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", host):
        raise ValueError("Use a simple SSH config alias, e.g. workbox")
    if not script.startswith("/") or not python:
        raise ValueError("Remote script must be an absolute Linux path")
    argv = [python, script]
    if remote_state:
        if not remote_state.startswith("/"):
            raise ValueError("Remote state directory must be absolute")
        argv += ["--state-dir", remote_state]
    argv.append("export")
    return ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=1", host, shlex.join(argv)]


def decode(raw, now, elapsed=0):
    if len(raw) > 1024 * 1024:
        raise ValueError("SSH snapshot exceeds 1 MiB")
    data = json.loads(raw)
    if data.get("schema_version") != 1 or not isinstance(data.get("rows"), list):
        raise ValueError("Unsupported remote snapshot")
    if len(data["rows"]) > MAX_ROWS:
        raise ValueError("Too many remote rows")
    result = []
    statuses = {"READY", "WORKING", "TOOL", "APPROVAL?", "COMPACT", "STOPPED",
                "TURN STOP", "INTERRUPTED", "CLOSED", "EXIT ERROR", "STALE", "NO HOOKS"}
    for i, item in enumerate(data["rows"]):
        if not isinstance(item, dict) or item.get("status") not in statuses:
            raise ValueError("Invalid remote row")
        # Rebuild an allowlist, never trust executable paths or local focus IDs.
        row = {k: clean(item.get(k), 512 if k in {"key", "session_id"} else 80)
               for k in ("key", "session_id", "name", "kind", "status", "last_event")}
        if not row["key"]:
            raise ValueError("Missing row key")
        ttl, age = float(item.get("valid_until", 0)), float(item.get("updated_at", 0))
        if not math.isfinite(ttl) or not math.isfinite(age) or ttl < 0 or age < 0:
            raise ValueError("Invalid remote timing")
        row.update(order=i, iterm_id="", tty="", run_id="", agent_id="", turn_id="",
                   herdr=bool(item.get("herdr")), updated_at=now - age - elapsed,
                   valid_until=now + max(0, min(ttl, 900) - elapsed))
        result.append(row)
    return result


def collect_once(store, alias, argv, runner=subprocess.run, now_fn=time.time):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", alias):
        raise ValueError("Invalid source label")
    started = now_fn()
    error = ""
    rows = None
    try:
        # A temporary file bounds memory even if a remote shell writes excessive output.
        import tempfile
        with tempfile.TemporaryFile() as output:
            result = runner(argv, stdout=output, stderr=subprocess.DEVNULL, timeout=12,
                            check=False)
            output.seek(0)
            raw = output.read(1024 * 1024 + 1)
        if result.returncode:
            raise RuntimeError("SSH failed; verify key, host trust, and remote path")
        now = now_fn()
        rows = decode(raw, now, max(0, now - started))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        error = clean(type(exc).__name__ + ": " + str(exc), 160)
    with store.transaction() as state:
        remote = state["remotes"].setdefault(alias, dict(rows=[], received_at=0))
        if rows is not None:
            remote.update(rows=rows, received_at=now_fn(), error="")
        else:
            remote["error"] = error
    return not error
