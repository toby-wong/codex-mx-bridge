"""Explicit Herdr-to-iTerm bindings; remote snapshots never grant focus authority."""
import json
import os
from pathlib import Path
import re
import uuid

from .state import atomic_json

CONFIG = "herdr-focus.json"
MAX_BINDINGS = 16
MAX_CONFIG_BYTES = 65536


def socket_path(value):
    value = str(value)
    if not value.startswith("/") or not 1 < len(value) <= 512 or not value.isprintable():
        raise ValueError("Use an absolute local Herdr socket path")
    return os.path.normpath(value)


def remote_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ValueError("Use a simple remote source alias or Herdr session name (up to 64 characters)")
    return value


def validate_remote(item):
    if not isinstance(item, dict):
        raise ValueError("Invalid remote Herdr binding")
    remote_name(item.get("source"))
    host = item.get("ssh_target")
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,254}", host):
        raise ValueError("Use a simple SSH target; configure ports and options in SSH config")
    path = item.get("herdr_path", "herdr")
    if (not isinstance(path, str) or
            (path != "herdr" and (not path.startswith("/") or not 1 < len(path) <= 512 or
                                 not path.isprintable()))):
        raise ValueError("Use herdr or an absolute remote Herdr executable path")
    session = item.get("remote_session", "")
    if session != "":
        remote_name(session)
    if iterm_id(item.get("iterm_id")) != item.get("iterm_id"):
        raise ValueError("Stored iTerm2 bindings must use a session UUID")
    return item


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
            not isinstance(value.get("bindings"), list) or len(value["bindings"]) > MAX_BINDINGS or
            not isinstance(value.get("remote_bindings", []), list) or
            len(value.get("remote_bindings", [])) > MAX_BINDINGS):
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
    seen = set()
    for item in value.get("remote_bindings", []):
        validate_remote(item)
        key = (item["source"], item.get("remote_session", ""))
        if key in seen:
            raise ValueError("Duplicate remote Herdr session binding")
        seen.add(key)
    return value


def outer_iterm(target=None, env=None):
    env = os.environ if env is None else env
    if target is None:
        if env.get("HERDR_ENV") == "1" or env.get("SSH_CONNECTION"):
            raise ValueError("Bind from the outer local iTerm2 shell, or pass its explicit --iterm-id")
        target = env.get("ITERM_SESSION_ID")
    return iterm_id(target)


def make_binding(path, target=None, env=None):
    return {"socket_path": socket_path(path), "iterm_id": outer_iterm(target, env)}


def bind(directory, path, target=None, env=None):
    binding = make_binding(path, target, env)
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


def bind_remote(directory, source, target=None, *, ssh_target=None, herdr_path="herdr",
                remote_session="", env=None):
    binding = validate_remote(dict(source=source, ssh_target=source if ssh_target is None else ssh_target,
                                   herdr_path=herdr_path, remote_session=remote_session,
                                   iterm_id=outer_iterm(target, env)))
    value = read_bindings(directory)
    bindings = [item for item in value.get("remote_bindings", [])
                if (item["source"], item.get("remote_session", "")) != (source, remote_session)]
    if len(bindings) >= MAX_BINDINGS:
        raise ValueError("At most 16 remote Herdr sessions can be bound")
    value["remote_bindings"] = bindings + [binding]
    atomic_json(Path(directory) / CONFIG, value)
    return value


def remove_remote(directory, source, remote_session=""):
    remote_name(source)
    if remote_session != "":
        remote_name(remote_session)
    value = read_bindings(directory)
    value["remote_bindings"] = [item for item in value.get("remote_bindings", [])
                                if (item["source"], item.get("remote_session", "")) != (source, remote_session)]
    atomic_json(Path(directory) / CONFIG, value)
    return value
