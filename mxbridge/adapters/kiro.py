"""Kiro CLI's five legacy hooks and their current trigger spellings."""
from .common import Event, identity, project

EVENTS = ("agentSpawn", "userPromptSubmit", "preToolUse", "postToolUse", "stop")
NAMES = dict(zip(EVENTS, ("SessionStart", "UserPromptSubmit", "PreToolUse",
                         "PostToolUse", "Stop")))
NAMES.update({name: name for name in NAMES.values()})
NAMES.update(AgentSpawn="SessionStart", SessionEnd="SessionEnd")
V3_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop",
             "SessionEnd")


def normalize(payload, instance=""):
    native = payload.get("hook_event_name")
    name = NAMES.get(native) if isinstance(native, str) else None
    if name is None:
        return None
    # A profile name, cwd or hook process ID cannot distinguish concurrent chats.
    return Event("kiro", name, native, identity(payload.get("session_id")),
                 project(payload, "Kiro"), instance=instance)
