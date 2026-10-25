"""Client-specific hook definitions and conservative configuration merging."""
import copy
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from .adapters import ADAPTERS, CLIENTS, LABELS
from .adapters.common import identity
from .adapters.kiro import V3_EVENTS
from .state import atomic_json

MARKER = "codex-mx-bridge:v1"
MARKERS = {"codex": MARKER, "claude": "codex-mx-bridge:claude:v1",
           "kiro": "codex-mx-bridge:kiro:v1"}


def definition(script, python=None, *, client="codex", kiro_format="v2", instance=""):
    if client not in CLIENTS or kiro_format not in {"v2", "v3"}:
        raise ValueError("Unsupported hook client or Kiro format")
    identity(instance, optional=True, limit=80)
    argv = [python or sys.executable, str(Path(script).resolve()), "hook"]
    if client != "codex":
        argv += ["--client", client]
    if instance:
        argv += ["--instance", instance]
    if client == "kiro":
        # A marker in our own argv needs no unsupported Kiro configuration field.
        argv += ["--hook-owner", MARKERS[client]]
    command = shlex.join(argv)
    if client != "codex":
        # Missing runtimes/entrypoints must not block a tool or continue a Stop.
        command += " >/dev/null 2>&1 || :"
    events = ADAPTERS[client].EVENTS
    if client == "kiro":
        if kiro_format == "v3":
            return {"hooks": [dict(name=MARKERS[client] + ":" + event, trigger=event,
                action=dict(type="command", command=command), timeout=2, enabled=True)
                for event in V3_EVENTS]}
        return {"hooks": {event: [dict(command=command, timeout_ms=2000, cache_ttl_seconds=0)]
                          for event in events}}
    handler = dict(type="command", command=command, timeout=2, statusMessage=MARKERS[client])
    if client == "claude":
        # Supported by Claude Code >= 2.1.295. The installer checks the version.
        handler["onFailure"] = "continue"
    return {"hooks": {event: [{"hooks": [copy.deepcopy(handler)]}] for event in events}}


def _owned_kiro(handler):
    action = handler.get("action", handler)
    if not isinstance(action, dict) or not isinstance(action.get("command"), str):
        return False
    try:
        argv = shlex.split(action["command"])
    except ValueError:
        return False
    return (len(argv) >= 3 and Path(argv[1]).name == "bridge.py" and argv[2] == "hook" and
            any(argv[i:i+2] == ["--hook-owner", MARKERS["kiro"]] for i in range(len(argv))) and
            any(argv[i:i+2] == ["--client", "kiro"] for i in range(len(argv))) and "hook" in argv)


def _handlers(value):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("Hook handlers must be an array of objects")
    return value


def merge(existing, proposed, *, client="codex", kiro_format="v2"):
    if not isinstance(existing, dict) or not isinstance(proposed, dict):
        raise ValueError("Hook configuration must be an object")
    if client not in CLIENTS or kiro_format not in {"v2", "v3"}:
        raise ValueError("Unsupported hook client or Kiro format")
    result = copy.deepcopy(existing)
    if client == "kiro" and kiro_format == "v3":
        if proposed.get("hooks") and not isinstance(existing.get("permissions"), dict) and any(
                field in existing for field in ("allowedTools", "toolsSettings")):
            raise ValueError("Kiro V3 skips unconverted 2.x trust settings; migrate the profile "
                             "with Kiro before installing v3 hooks")
        hooks = _handlers(result.setdefault("hooks", []))
        result["hooks"] = [h for h in hooks if not _owned_kiro(h)]
        result["hooks"].extend(copy.deepcopy(_handlers(proposed.get("hooks", []))))
        return result
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Existing hooks must be an object; array-form Kiro profiles need --kiro-format v3")
    # Strip only our own handlers, including commands from an older install path.
    for event, groups in list(hooks.items()):
        _handlers(groups)
        if client == "kiro":
            hooks[event] = [h for h in groups if not _owned_kiro(h)]
            continue
        kept = []
        for group in groups:
            group = copy.deepcopy(group)
            group["hooks"] = [h for h in _handlers(group.get("hooks", []))
                              if h.get("statusMessage") != MARKERS[client]]
            if group["hooks"]:
                kept.append(group)
        hooks[event] = kept
    for event, groups in proposed.get("hooks", {}).items():
        hooks.setdefault(event, []).extend(copy.deepcopy(groups))
    return result


def install(path, proposed, apply=False, *, client="codex", kiro_format="v2"):
    path = Path(path).expanduser()
    before = path.read_bytes() if path.exists() else None
    existing = json.loads(before) if before is not None else {}
    result = merge(existing, proposed, client=client, kiro_format=kiro_format)
    if result == existing or (before is None and not proposed):
        return result
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse to overwrite a concurrent Herdr/Codex configuration edit.
        if (path.read_bytes() if path.exists() else None) != before:
            raise RuntimeError("Hook configuration changed during install; retry")
        if before is not None:
            backup = path.with_name(path.name + f".mx-backup-{time.time_ns()}")
            shutil.copy2(path, backup)
        atomic_json(path, result)
    return result


def target(client, *, codex_home=None, claude_settings=None, agent_config=None,
           kiro_format="v2", instance="", require_existing=True):
    """Resolve one explicit scope; Kiro never guesses which profile to rewrite."""
    if client not in CLIENTS or kiro_format not in {"v2", "v3"}:
        raise ValueError("Unsupported hook client or Kiro format")
    identity(instance, optional=True, limit=80)
    if client == "codex":
        path = Path(codex_home or os.environ.get("CODEX_HOME", Path.home()/".codex"))/"hooks.json"
    elif client == "claude":
        path = (Path(claude_settings) if claude_settings else
                Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home()/".claude"))/"settings.json")
    else:
        if agent_config is None:
            raise ValueError("Kiro requires --agent-config with an existing user-owned agent profile")
        path = Path(agent_config).expanduser()
        if require_existing and not path.is_file():
            raise ValueError("Kiro --agent-config must name an existing agent profile")
    return dict(client=client, path=str(path.expanduser().resolve()),
                kiro_format=kiro_format, instance=instance)


def require_cli(client, *, runner=subprocess.run, which=shutil.which):
    name = "kiro-cli" if client == "kiro" else client
    executable = which(name)
    if not executable:
        raise ValueError(f"{LABELS[client]} CLI is missing from PATH; install it first, then rerun")
    if client == "codex":
        return executable
    result = runner([executable, "--version"], capture_output=True, text=True, timeout=10)
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout or "")
    minimum = (2, 1, 295) if client == "claude" else (2, 0, 0)
    if result.returncode or not match or tuple(map(int, match.groups())) < minimum:
        version = ".".join(map(str, minimum))
        raise ValueError(f"{LABELS[client]} CLI {version} or later is required for these hooks")
    return executable


def validate_kiro_profile(value, executable, *, runner=subprocess.run, cwd=None):
    """Ask Kiro to validate a temporary profile before editing the real one."""
    with tempfile.TemporaryDirectory(prefix="mx-kiro-validate-") as folder:
        path = Path(folder)/"bridge-check.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        result = runner([executable, "agent", "validate", "--path", str(path)],
                        cwd=cwd, capture_output=True, text=True, timeout=15)
    if result.returncode:
        # Validation output may contain user configuration. Keep it off stdout.
        raise ValueError("Kiro rejected the merged profile; check its format with kiro-cli agent validate")


def targets_from_manifest(manifest):
    """Read new manifests and the original Codex-only installation format."""
    if not isinstance(manifest, dict):
        raise ValueError("Invalid installation manifest")
    targets = manifest.get("hook_targets")
    if targets is None:
        if (not isinstance(manifest.get("codex_home"), str) or
                not Path(manifest["codex_home"]).is_absolute()):
            raise ValueError("Invalid legacy Codex installation manifest")
        targets = [dict(client="codex", path=str(Path(manifest["codex_home"])/"hooks.json"),
                        kiro_format="v2", instance="")]
    if not isinstance(targets, list) or len(targets) > 32:
        raise ValueError("Invalid installed hook targets")
    result = []
    for item in targets:
        if (not isinstance(item, dict) or item.get("client") not in CLIENTS or
                not isinstance(item.get("path"), str) or not Path(item["path"]).is_absolute() or
                item.get("kiro_format", "v2") not in {"v2", "v3"}):
            raise ValueError("Invalid installed hook target")
        result.append(dict(client=item["client"], path=item["path"],
                           kiro_format=item.get("kiro_format", "v2"),
                           instance=identity(item.get("instance", ""), optional=True, limit=80)))
    return result


def combine_targets(previous, selected, *, remove=False):
    keys = {(t["client"], t["path"]) for t in selected}
    result = [t for t in previous if (t["client"], t["path"]) not in keys]
    if not remove:
        result.extend(selected)
    if len(result) > 32:
        raise ValueError("At most 32 hook targets can be installed")
    return result


def record_target(script, selected, *, remove=False, apply=True):
    """Keep update.sh aware of hooks installed through a staged bridge command."""
    release = Path(script).resolve().parent
    if release.parent.name != "releases":
        return
    path = release.parent.parent/"installation.json"
    if not path.is_file():
        return
    with path.open("rb") as stream:
        before = stream.read(1024 * 1024 + 1)
        if len(before) > 1024 * 1024:
            raise ValueError("Installation manifest exceeds 1 MiB")
    manifest = json.loads(before)
    manifest["hook_targets"] = combine_targets(targets_from_manifest(manifest), [selected], remove=remove)
    if not apply:
        return
    if path.read_bytes() != before:
        raise RuntimeError("Installation manifest changed during hook registration; retry")
    atomic_json(path, manifest)
