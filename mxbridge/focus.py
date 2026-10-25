"""Explicit local Herdr-to-iTerm bindings; never infer a client from server env."""
import json
import os
from pathlib import Path
import uuid

from .state import atomic_json

CONFIG = "herdr-focus.json"
MAX_BINDINGS = 16
MAX_CONFIG_BYTES = 65536


def socket_path(value):
    value = str(value)
    if not value.startswith("/") or len(value) > 512 or not value.isprintable():
        raise ValueError("Use an absolute local Herdr socket path")
    return os.path.normpath(value)


def iterm_id(value):
    if not isinstance(value, str):
        raise ValueError("An iTerm2 session ID is required")
    target = value.split(":")[-1]
    try:
        if str(uuid.UUID(target)).lower() != target.lower():
            raise ValueError("Expected a hyphenated UUID")
    except (ValueError, AttributeError) as exc:
        raise ValueError("Use the iTerm2 session UUID, or its ITERM_SESSION_ID value") from exc
    # Preserve iTerm's spelling; only remove the window/tab prefix.
    return target


def read_bindings(directory):
    path = Path(directory) / CONFIG
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return {"schema_version": 1, "bindings": []}
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("Herdr focus configuration exceeds 64 KiB")
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get("schema_version") != 1 or
            not isinstance(value.get("bindings"), list) or len(value["bindings"]) > MAX_BINDINGS):
        raise ValueError("Invalid Herdr focus configuration")
    seen = set()
    for item in value["bindings"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid Herdr focus binding")
        path = socket_path(item.get("socket_path", ""))
        if iterm_id(item.get("iterm_id")) != item.get("iterm_id"):
            raise ValueError("Stored iTerm2 bindings must use a session UUID")
        if path in seen:
            raise ValueError("Duplicate Herdr socket binding")
        seen.add(path)
    return value


def bind(directory, path, target=None, env=None):
    env = os.environ if env is None else env
    if target is None:
        if env.get("HERDR_ENV") == "1" or env.get("SSH_CONNECTION"):
            raise ValueError("Bind from the outer local iTerm2 shell, or pass its explicit --iterm-id")
        target = env.get("ITERM_SESSION_ID")
    binding = {"socket_path": socket_path(path), "iterm_id": iterm_id(target)}
    value = read_bindings(directory)
    value["bindings"] = [item for item in value["bindings"]
                         if socket_path(item["socket_path"]) != binding["socket_path"]]
    if len(value["bindings"]) >= MAX_BINDINGS:
        raise ValueError("At most 16 Herdr sessions can be bound")
    value["bindings"].append(binding)
    atomic_json(Path(directory) / CONFIG, value)
    return value


def remove(directory, path):
    path = socket_path(path)
    value = read_bindings(directory)
    value["bindings"] = [item for item in value["bindings"] if socket_path(item["socket_path"]) != path]
    atomic_json(Path(directory) / CONFIG, value)
    return value
