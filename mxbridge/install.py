"""Non-destructive hooks.json merging. Never changes config.toml or hook trust."""
import copy
import json
from pathlib import Path
import shlex
import shutil
import sys
import time
from .state import EVENTS, atomic_json

MARKER = "codex-mx-bridge:v1"


def definition(script, python=None):
    command = shlex.join([python or sys.executable, str(Path(script).resolve()), "hook"])
    return {"hooks": {event: [{"hooks": [dict(type="command", command=command,
        timeout=2, statusMessage=MARKER)]}] for event in EVENTS}}


def merge(existing, proposed):
    result = copy.deepcopy(existing)
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Existing hooks must be an object")
    # Strip only our own handlers, including commands from an older install path.
    for event, groups in list(hooks.items()):
        kept = []
        for group in groups:
            group = copy.deepcopy(group)
            group["hooks"] = [h for h in group.get("hooks", [])
                              if h.get("statusMessage") != MARKER]
            if group["hooks"]:
                kept.append(group)
        hooks[event] = kept
    for event, groups in proposed.get("hooks", {}).items():
        hooks.setdefault(event, []).extend(copy.deepcopy(groups))
    return result


def install(path, proposed, apply=False):
    path = Path(path).expanduser()
    before = path.read_bytes() if path.exists() else None
    existing = json.loads(before) if before is not None else {}
    result = merge(existing, proposed)
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse to overwrite a concurrent Herdr/Codex configuration edit.
        if (path.read_bytes() if path.exists() else None) != before:
            raise RuntimeError("hooks.json changed during install; retry")
        if before is not None:
            backup = path.with_name(path.name + f".mx-backup-{time.time_ns()}")
            shutil.copy2(path, backup)
        atomic_json(path, result)
    return result
