"""Private, locked, atomic file transport. Does not read agent transcripts."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time
from .adapters import LABELS, normalize
from .adapters.codex import EVENTS
from .adapters.common import clean

FINAL = {"CLOSED", "EXIT ERROR", "STOPPED"}
MAX_ROWS = 256
EVENT_STATUS = {
    "SessionStart": "READY", "SessionEnd": "CLOSED", "UserPromptSubmit": "WORKING",
    "PreToolUse": "TOOL", "PermissionRequest": "APPROVAL?", "PostToolUse": "WORKING",
    "PostToolUseFailure": "WORKING", "PreCompact": "COMPACT", "PostCompact": "WORKING",
    "SubagentStart": "WORKING", "SubagentStop": "STOPPED", "Stop": "TURN STOP",
    "StopFailure": "TURN ERROR", "Interrupt": "INTERRUPTED",
}
STATUSES = set(EVENT_STATUS.values()) | {"EXIT ERROR", "STALE", "NO HOOKS"}


def default_dir():
    if os.environ.get("MX_CODEX_STATE_DIR"):
        return Path(os.environ["MX_CODEX_STATE_DIR"]).expanduser()
    # Deliberately identical on macOS/Linux; the plugin uses this default on Mac.
    return Path.home() / ".local" / "state" / "codex-mx-bridge"


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


def focus_target(env):
    # Herdr owns a virtual terminal. Its server may inherit an obsolete iTerm ID.
    herdr = env.get("HERDR_ENV") == "1"
    local = not env.get("SSH_CONNECTION")
    socket = env.get("HERDR_SOCKET_PATH", "")
    if (not isinstance(socket, str) or not socket.startswith("/") or
            len(socket) > 512 or not socket.isprintable()):
        socket = ""
    return dict(herdr=herdr,
                herdr_socket=os.path.normpath(socket) if herdr and local and socket else "",
                iterm_id=clean(env.get("ITERM_SESSION_ID"), 256) if local and not herdr else "",
                tty=clean(env.get("MX_CODEX_TTY"), 128) if local and not herdr else "")


def new_row(state, key, session, name, now, env, kind="session", client="codex", instance=""):
    state["next_order"] += 1
    row = dict(key=key, session_id=session, name=clean(name) or LABELS[client], kind=kind,
               client=client, source_instance=instance,
               order=state["next_order"], status="READY", last_event="",
               created_at=now, updated_at=now, valid_until=now + 900, turn_id="",
               run_id=clean(env.get("MX_CODEX_RUN_ID"), 128), agent_id="",
               **focus_target(env))
    state["rows"].append(row)
    return row


def apply_event(state, payload, env=None, now=None, *, client="codex", instance=""):
    env = os.environ if env is None else env
    now = time.time() if now is None else now
    observed = normalize(client, payload, instance)
    if observed is None:
        return False
    event, sid, agent = observed.name, observed.session_id, observed.child_id
    key = observed.key
    # A nested CLI must not join another client's launcher heartbeat/exit scope.
    run_id = (clean(env.get("MX_CODEX_RUN_ID"), 128)
              if env.get("MX_BRIDGE_CLIENT", "codex") == client and
              env.get("MX_BRIDGE_INSTANCE", "") == instance else "")
    state["rows"] = [r for r in state["rows"] if not (
        run_id and r["key"] == "@run/" + run_id and
        r.get("client", "codex") == client and r.get("source_instance", "") == instance)]
    row = next((r for r in state["rows"] if r["key"] == key and
                r.get("client", "codex") == client and
                r.get("source_instance", "") == instance), None)
    if row is None:
        name = observed.label if agent else clean(env.get("MX_CODEX_LABEL")) or observed.label
        row = new_row(state, key, sid, name, now, env, "subagent" if agent else "session",
                      client, instance)
        row["agent_id"] = agent
        row["run_id"] = run_id
    # A compact SessionStart may occur mid-turn; do not reset the observed state.
    status = EVENT_STATUS[event]
    turn = observed.turn_id
    # A tool result from an older turn must not undo the latest turn's Stop.
    tool_event = event in {"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"}
    if client != "codex" and row["turn_id"] and turn and turn != row["turn_id"]:
        if event not in {"UserPromptSubmit", "SessionStart", "SubagentStart"}:
            return False
    if tool_event:
        if row["turn_id"] and turn and turn != row["turn_id"]:
            return False
        stopped = {"TURN STOP", "TURN ERROR", "INTERRUPTED", "CLOSED", "EXIT ERROR", "STOPPED"}
        if row["status"] in stopped:
            # Synchronous PreToolUse is fresh activity after a Stop hook's
            # continuation. A late result alone must not restart the animation.
            if client == "codex" or event != "PreToolUse" or row["status"] in {"CLOSED", "EXIT ERROR"}:
                return False
    if event == "SessionStart" and observed.source == "compact":
        status = row["status"]
    if event == "SessionStart":
        # Resume/fork can attach the same Codex identity to a different terminal.
        # Never keep a previous attachment's iTerm target or launcher identity.
        row.update(run_id=run_id, **focus_target(env))
    elif row.get("herdr") and env.get("HERDR_ENV") == "1":
        # Populate old rows after an upgrade, without restarting an active chat.
        row.update(focus_target(env))
    row.update(status=status, last_event=observed.native_name, updated_at=now,
               valid_until=now + (45 if run_id else 900))
    if run_id:
        row["run_id"] = run_id
    if turn:
        row["turn_id"] = turn
    elif client != "codex" and (event == "UserPromptSubmit" or
                               event == "SessionStart" and observed.source != "compact"):
        row["turn_id"] = ""
    state.setdefault("hook_health", {})[client] = dict(last_received_at=now,
                                                       last_event=observed.native_name)
    return True


def run_start(state, run_id, name, env, now, client="codex", instance=""):
    new_row(state, "@run/" + run_id, "", name, now, env, client=client, instance=instance).update(
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
        copy["iterm_id"] = copy["tty"] = copy["herdr_socket"] = ""
        copy["valid_until"] = max(0, copy["valid_until"] - now)
        copy["updated_at"] = max(0, now - copy["updated_at"])
        # Like activity time, creation travels as an age to avoid clock skew.
        # Missing legacy timestamps remain unknown, never inferred from activity.
        if copy.get("created_at") is not None:
            copy["created_at"] = max(0, now - copy["created_at"])
        rows.append(copy)
    return dict(schema_version=1, rows=rows)
