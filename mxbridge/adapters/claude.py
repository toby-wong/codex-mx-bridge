"""Claude Code lifecycle hooks; never retain prompts or tool contents."""
from .common import Event, clean, identity, project

EVENTS = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
    "PermissionRequest", "PostToolUse", "PostToolUseFailure",
    "PreCompact", "PostCompact", "SubagentStart", "SubagentStop",
    "Stop", "StopFailure",
)


def normalize(payload, instance=""):
    name = payload.get("hook_event_name")
    if name not in EVENTS:
        return None
    sid = identity(payload.get("session_id"))
    # Tool hooks also fire inside subagents and carry their identity.
    child = identity(payload.get("agent_id"), optional=True)
    if name.startswith("Subagent") and not child:
        raise ValueError("Missing Claude child identity")
    label = (clean(payload.get("agent_type")) or "Subagent") if child else project(payload, "Claude")
    return Event("claude", name, name, sid, label, child,
                 identity(payload.get("prompt_id"), optional=True),
                 clean(payload.get("source")), instance)
