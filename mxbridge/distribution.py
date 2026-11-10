"""Validate the plugin shipped in a release before activating it."""
import hashlib
import json
from pathlib import Path

from . import __version__

PLUGIN_FILES = {
    "bin/CodexMxPlugin.dll",
    "bin/CodexMxPlugin.deps.json",
    "focus.applescript",
    "metadata/LoupedeckPackage.yaml",
    "metadata/Icon256x256.png",
}


def validate_plugin(root):
    root = Path(root)
    record = json.loads((root / "distribution.json").read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("schema_version") != 1 or
            record.get("version") != __version__ or not isinstance(record.get("plugin"), dict) or
            set(record["plugin"]) != PLUGIN_FILES):
        raise ValueError("The release's plugin manifest is invalid or belongs to a different version")
    folder = root / "prebuilt/CodexMx"
    files = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    if (files != PLUGIN_FILES or any(p.is_symlink() for p in folder.rglob("*")) or folder.is_symlink() or
            not folder.resolve().is_relative_to(root.resolve())):
        raise ValueError("The prebuilt plugin contains unexpected or missing files")
    for name, digest in record["plugin"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"The prebuilt plugin checksum does not match: {name}")
    return folder
