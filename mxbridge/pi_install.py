"""Install one checksummed, bridge-owned Pi extension without editing Pi settings."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import time
import json

MARKER = "// codex-mx-bridge:pi:v1 sha256:"
PLACEHOLDER = "const DEFAULT_OPTIONS = { command: [] };"


def definition(script, python, instance=""):
    script = Path(script).resolve()
    source = (script.parent / "integrations/pi/codex-mx-bridge.ts").read_text(encoding="utf-8")
    command = [str(python), str(script), "hook", "--client", "pi"]
    if instance:
        command += ["--instance", instance]
    if source.count(PLACEHOLDER) != 1:
        raise ValueError("Pi extension install placeholder is missing")
    content = source.replace(PLACEHOLDER, "const DEFAULT_OPTIONS = " +
                             json.dumps(dict(command=command), ensure_ascii=True) + ";")
    digest = hashlib.sha256(content.encode()).hexdigest()
    return MARKER + digest + "\n" + content


def install(path, proposed, apply=False):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError("Pi extension target is a symlink; choose a separate --pi-agent-dir")
    before = path.read_bytes() if path.exists() else None
    if before is not None:
        header, _, content = before.partition(b"\n")
        expected = (MARKER + hashlib.sha256(content).hexdigest()).encode()
        if header != expected:
            raise ValueError("Pi extension contains unowned or edited content; existing file was kept")
    if not isinstance(proposed, str) and proposed != {}:
        raise ValueError("Invalid Pi extension definition")
    after = proposed.encode() if proposed else None
    result = dict(path=str(path), installed=bool(after), changed=before != after)
    if not apply or before == after:
        return result
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.read_bytes() if path.exists() else None) != before:
        raise RuntimeError("Pi extension changed during install; retry")
    if before is not None:
        shutil.copy2(path, path.with_name(path.name + f".mx-backup-{time.time_ns()}"))
    if after is None:
        path.unlink()
    else:
        fd, temporary = tempfile.mkstemp(prefix=".mx-pi-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return result
