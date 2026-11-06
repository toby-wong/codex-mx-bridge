"""Content-free observations from the bridge's Pi extension, protocol version 1."""
from dataclasses import dataclass
import math
from .common import Event, clean, identity, project

EVENTS = (
    "session_start", "session_info_changed", "session_shutdown", "agent_start",
    "agent_settled", "tool_execution_start", "tool_execution_end", "ui_prompt_start",
    "ui_prompt_end", "session_before_compact", "session_compact",
    "session_compact_failed", "heartbeat", "child_started",
)
STATUSES = {"READY", "WORKING", "TOOL", "WAITING", "COMPACT", "TURN STOP",
            "TURN ERROR", "INTERRUPTED", "CLOSED"}
MAX_PATH = 2048


def session_path(value, *, optional=True):
    value = identity(value, optional=optional, limit=MAX_PATH)
    if value and not value.startswith("/"):
        raise ValueError("Pi session path must be absolute")
    return value


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1e12:
        raise ValueError("Invalid Pi timestamp")
    return value


def counter(value):
    if type(value) is not int or not 1 <= value <= 9007199254740991:
        raise ValueError("Invalid Pi sequence")
    return value


@dataclass(frozen=True)
class Observation(Event):
    fallback_name: str = ""
    session_path: str = ""
    parent_path: str = ""
    kind: str = "session"
    role: str = ""
    launch_id: str = ""
    attachment: str = ""
    started_at: float = 0
    sequence: int = 1
    status: str = "READY"
    activity_at: float = 0
    created_at: float = 0
    mode: str = "headless"
    child: dict | None = None


def normalize(payload, instance=""):
    name = payload.get("hook_event_name")
    if name not in EVENTS:
        return None
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("Unsupported Pi observation")
    status = payload.get("status")
    kind = payload.get("kind", "session")
    mode = payload.get("mode", "headless")
    if status not in STATUSES or kind not in {"session", "subagent"} or mode not in {"tui", "headless"}:
        raise ValueError("Invalid Pi state")
    launch_id = identity(payload.get("launch_id"), optional=True)
    if kind == "subagent" and not launch_id:
        raise ValueError("Missing Pi child launch identity")
    child = None
    if name == "child_started":
        value = payload.get("child")
        if not isinstance(value, dict):
            raise ValueError("Missing Pi child association")
        child = dict(path=session_path(value.get("session_path"), optional=False),
                     launch_id=identity(value.get("launch_id")))
    # child_id stays empty: each Pi child has its own native session identity.
    return Observation(
        client="pi", name=name, native_name=name,
        session_id=identity(payload.get("session_id")),
        label=clean(payload.get("name")) or project(payload, "Pi"), instance=instance,
        fallback_name=clean(payload.get("fallback_name")) or project(payload, "Pi"),
        source=clean(payload.get("reason")),
        session_path=session_path(payload.get("session_path")),
        parent_path=session_path(payload.get("parent_session_path")),
        kind=kind, role=clean(payload.get("agent_role")), launch_id=launch_id,
        attachment=identity(payload.get("attachment_id"), limit=128),
        started_at=number(payload.get("attachment_started_at")),
        sequence=counter(payload.get("sequence")), status=status,
        activity_at=number(payload.get("activity_at")), created_at=number(payload.get("created_at")),
        mode=mode, child=child)
