"""Preserve the original Codex hook names and identity behavior."""
from .common import Event, clean, project

EVENTS = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
    "PermissionRequest", "PostToolUse", "PreCompact", "PostCompact",
    "SubagentStart", "SubagentStop", "Stop", "Interrupt",
)


def normalize(payload, instance=""):
    name = payload.get("hook_event_name")
    sid = clean(payload.get("session_id"), 512)
    if name not in EVENTS or not sid:
        return None
    child = clean(payload.get("agent_id"), 512) if name.startswith("Subagent") else ""
    if name.startswith("Subagent") and not child:
        return None
    label = (clean(payload.get("agent_type")) or "Subagent") if child else project(payload, "Codex")
    return Event("codex", name, name, sid, label, child,
                 clean(payload.get("turn_id"), 512), clean(payload.get("source")), instance)
