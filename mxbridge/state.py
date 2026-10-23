"""Private, locked, atomic file transport. Does not read Codex transcripts."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time

EVENTS = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
    "PermissionRequest", "PostToolUse", "PreCompact", "PostCompact",
    "SubagentStart", "SubagentStop", "Stop", "Interrupt",
)
FINAL = {"CLOSED", "EXIT ERROR", "STOPPED"}
MAX_ROWS = 256


def default_dir():
    if os.environ.get("MX_CODEX_STATE_DIR"):
        return Path(os.environ["MX_CODEX_STATE_DIR"]).expanduser()
    # Deliberately identical on macOS/Linux; the plugin uses this default on Mac.
    return Path.home() / ".local" / "state" / "codex-mx-bridge"


def clean(value, limit=80):
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value if c.isprintable())[:limit]


def empty():
    return {"schema_version": 1, "revision": 0, "next_order": 0,
            "rows": [], "remotes": {}, "dropped_rows": 0}


def atomic_json(path, value):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".mx-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Store:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else default_dir()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            os.chmod(self.directory, 0o700)
        self.path = self.directory / "state.json"

    def read(self):
        try:
            with self.path.open(encoding="utf-8") as f:
                result = json.load(f)
        except FileNotFoundError:
            return empty()
        if result.get("schema_version") != 1:
            raise ValueError("Unsupported state schema; keep file for diagnosis")
        return result

    @contextmanager
    def transaction(self, timeout=0.4):
        # flock on macOS/Linux. Windows locking exists solely for portable tests.
        with (self.directory / "state.lock").open("a+b") as lock:
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            end = time.monotonic() + timeout
            while True:
                try:
                    if os.name == "posix":
                        import fcntl
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    else:
                        import msvcrt
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= end:
                        raise TimeoutError("Bridge state lock busy")
                    time.sleep(0.01)
            try:
                state = self.read()
                yield state
                state["revision"] += 1
                while len(state["rows"]) > MAX_ROWS:
                    state["rows"].pop(0)
                    state["dropped_rows"] += 1
                atomic_json(self.path, state)
            finally:
                if os.name == "posix":
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                else:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def new_row(state, key, session, name, now, env, kind="session"):
    state["next_order"] += 1
    # Herdr owns a virtual terminal. Its server may inherit an obsolete iTerm ID.
    can_focus = env.get("HERDR_ENV") != "1" and not env.get("SSH_CONNECTION")
    row = dict(key=key, session_id=session, name=clean(name) or "Codex", kind=kind,
               order=state["next_order"], status="READY", last_event="",
               updated_at=now, valid_until=now + 900, turn_id="",
               run_id=clean(env.get("MX_CODEX_RUN_ID"), 128), agent_id="",
               iterm_id=clean(env.get("ITERM_SESSION_ID"), 256) if can_focus else "",
               tty=clean(env.get("MX_CODEX_TTY"), 128) if can_focus else "",
               herdr=env.get("HERDR_ENV") == "1")
    state["rows"].append(row)
    return row


def apply_event(state, payload, env=None, now=None):
    env = os.environ if env is None else env
    now = time.time() if now is None else now
    event = payload.get("hook_event_name")
    sid = clean(payload.get("session_id"), 512)
    if event not in EVENTS or not sid:
        return False
    agent = clean(payload.get("agent_id"), 512) if event.startswith("Subagent") else ""
    if event.startswith("Subagent") and not agent:
        return False
    key = sid + ("/agent/" + agent if agent else "")
    run_id = clean(env.get("MX_CODEX_RUN_ID"), 128)
    state["rows"] = [r for r in state["rows"] if r["key"] != "@run/" + run_id]
    row = next((r for r in state["rows"] if r["key"] == key), None)
    if row is None:
        name = clean(env.get("MX_CODEX_LABEL")) or Path(str(payload.get("cwd") or "Codex")).name
        if agent:
            name = clean(payload.get("agent_type")) or "Subagent"
        row = new_row(state, key, sid, name, now, env, "subagent" if agent else "session")
        row["agent_id"] = agent
    # A compact SessionStart may occur mid-turn; do not reset the observed state.
    status = {
        "SessionStart": "READY", "SessionEnd": "CLOSED", "UserPromptSubmit": "WORKING",
        "PreToolUse": "TOOL", "PermissionRequest": "APPROVAL?", "PostToolUse": "WORKING",
        "PreCompact": "COMPACT", "PostCompact": "WORKING", "SubagentStart": "WORKING",
        "SubagentStop": "STOPPED", "Stop": "TURN STOP", "Interrupt": "INTERRUPTED",
    }[event]
    turn = clean(payload.get("turn_id"), 512)
    # A tool result from an older turn must not undo the latest turn's Stop.
    if event in {"PreToolUse", "PostToolUse", "PermissionRequest"}:
        if row["turn_id"] and turn and turn != row["turn_id"]:
            return False
        if row["status"] in {"TURN STOP", "INTERRUPTED", "CLOSED"}:
            return False
    if event == "SessionStart" and payload.get("source") == "compact":
        status = row["status"]
    row.update(status=status, last_event=event, updated_at=now,
               valid_until=now + (45 if run_id else 900))
    if run_id:
        row["run_id"] = run_id
    if turn:
        row["turn_id"] = turn
    return True


def run_start(state, run_id, name, env, now):
    new_row(state, "@run/" + run_id, "", name, now, env).update(
        status="NO HOOKS", last_event="LauncherStart", valid_until=now + 45)


def run_update(state, run_id, now, exit_code=None):
    for row in state["rows"]:
        if row["run_id"] != run_id:
            continue
        if exit_code is None:
            # A heartbeat proves only that the child process exists, not progress.
            row["valid_until"] = now + 45
        else:
            row.update(status="CLOSED" if exit_code == 0 else "EXIT ERROR",
                       last_event="LauncherExit", updated_at=now, valid_until=0)


def export_snapshot(state, now=None):
    now = time.time() if now is None else now
    rows = []
    for row in state["rows"]:
        copy = dict(row)
        if copy["status"] not in FINAL and now > copy["valid_until"]:
            copy["status"] = "STALE"
        # Focus metadata never travels from the remote host.
        copy["iterm_id"] = copy["tty"] = ""
        copy["valid_until"] = max(0, copy["valid_until"] - now)
        copy["updated_at"] = max(0, now - copy["updated_at"])
        rows.append(copy)
    return dict(schema_version=1, rows=rows)
