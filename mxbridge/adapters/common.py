"""Small, content-free event contract shared by command-hook adapters."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

CLIENTS = ("codex", "claude", "kiro")
LABELS = {"codex": "Codex", "claude": "Claude", "kiro": "Kiro"}


def clean(value, limit=80):
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value if c.isprintable())[:limit]


def identity(value, *, optional=False, limit=512):
    if optional and (value is None or value == ""):
        return ""
    if (not isinstance(value, str) or not value.strip() or
            len(value) > limit or not value.isprintable()):
        raise ValueError("Invalid hook identity")
    return value


def project(payload, fallback):
    cwd = payload.get("cwd")
    return clean(Path(cwd).name) if isinstance(cwd, str) and cwd else fallback


@dataclass(frozen=True)
class Event:
    client: str
    name: str
    native_name: str
    session_id: str
    label: str
    child_id: str = ""
    turn_id: str = ""
    source: str = ""
    instance: str = ""

    @property
    def key(self):
        if self.client == "codex" and not self.instance:
            return self.session_id + ("/agent/" + self.child_id if self.child_id else "")
        # Hash complete validated IDs, not truncated strings or delimiter joins.
        value = json.dumps([self.client, self.instance, self.session_id, self.child_id],
                           ensure_ascii=True, separators=(",", ":"))
        return "@client/" + self.client + "/" + hashlib.sha256(value.encode()).hexdigest()
