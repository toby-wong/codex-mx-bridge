#!/usr/bin/env python3.15
"""Build verified release assets and render the Homebrew formula."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mxbridge import __version__
from mxbridge.distribution import PLUGIN_FILES, validate_plugin
from scripts.install_local import source_files

REPOSITORY = "toby-wong/codex-mx-bridge"
LOGI_VERSION = "6.1.4.22672"


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_version(tag, root=ROOT):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) or tag != "v" + __version__:
        raise ValueError(f"Release tag must be v{__version__}")
    project = tomllib.loads((root / "pyproject.toml").read_text())
    metadata = (root / "plugin/package/metadata/LoupedeckPackage.yaml").read_text()
    if (project["project"]["version"] != __version__ or
            not re.search(rf"(?m)^version:\s*{re.escape(__version__)}\s*$", metadata)):
        raise ValueError("Python, project, and plugin versions must agree before release")


def formula(url, digest, version=__version__, template=None):
    if (not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or
            not re.fullmatch(r"[0-9a-f]{64}", digest) or
            not re.fullmatch(r"(?:https|file)://[^\s\"'\\]+", url)):
        raise ValueError("Invalid formula URL, version, or SHA256")
    template = template or ROOT / "packaging/homebrew/codex-mx-bridge.rb.in"
    text = Path(template).read_text()
    for key, value in dict(URL=url, SHA256=digest, VERSION=version).items():
        text = text.replace(f"@@{key}@@", value)
    if "@@" in text:
        raise ValueError("Unexpanded formula template field")
    return text


def archive(source, output):
    """Keep tar metadata deterministic; checksums still cover the compiled bytes."""
    with Path(output).open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as tar:
            for path in [source, *sorted(source.rglob("*"))]:
                if path.is_symlink():
                    raise ValueError("Release payloads must not contain symlinks")
                item = tar.gettarinfo(str(path), arcname=path.relative_to(source.parent).as_posix())
                item.uid = item.gid = item.mtime = 0
                item.uname = item.gname = ""
                item.mode = 0o755 if path.is_dir() or path.suffix == ".sh" else 0o644
                if path.is_file():
                    with path.open("rb") as stream:
                        tar.addfile(item, stream)
                else:
                    tar.addfile(item)


def package(root, plugin, output, tag):
    check_version(tag, root)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mx-release-") as folder:
        source = Path(folder) / f"codex-mx-bridge-{__version__}"
        source.mkdir()
        for path in source_files(root):
            relative = path.relative_to(root)
            if (relative.parts[0] == "prebuilt" or relative.parts[:2] == ("docs", "assets") or
                    relative.name in {"distribution.json", "homebrew.json"}):
                continue
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        digests = {}
        for name in sorted(PLUGIN_FILES):
            target = source / "prebuilt/CodexMx" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(plugin / name, target)
            digests[name] = checksum(target)
        (source / "distribution.json").write_text(json.dumps(
            dict(schema_version=1, version=__version__, sdk_tool=LOGI_VERSION, plugin=digests), indent=2) + "\n")
        validate_plugin(source)
        asset = output / f"codex-mx-bridge-{__version__}.tar.gz"
        archive(source, asset)
    return asset


def build(args):
    check_version(args.tag)
    tools = args.tool_dir.absolute()
    tool = tools / ("logiplugintool.exe" if sys.platform == "win32" else "logiplugintool")
    if not tool.is_file():
        subprocess.run(["dotnet", "tool", "install", "LogiPluginTool", "--version", LOGI_VERSION,
                        "--tool-path", str(tools)], check=True)
    sdks = list(tools.glob(f".store/logiplugintool/{LOGI_VERSION}/logiplugintool/{LOGI_VERSION}/tools/net8.0/any/PluginApi.dll"))
    if len(sdks) != 1:
        raise ValueError("The pinned LogiPluginTool .NET 8 SDK is missing")
    subprocess.run(["dotnet", "build", str(ROOT / "plugin/CodexMxPlugin.csproj"), "-c", "Release",
                    "-p:PluginApiPath=" + str(sdks[0]), "-p:Version=" + __version__], check=True, cwd=ROOT)
    plugin = ROOT / "plugin/bin/Release/package"
    args.output.mkdir(parents=True, exist_ok=True)
    packed = args.output.absolute() / f"CodexMx_{__version__.replace('.', '_')}.lplug4"
    subprocess.run([str(tool), "pack", str(plugin), str(packed)], check=True)
    subprocess.run([str(tool), "verify", str(packed)], check=True)
    asset = package(ROOT, plugin, args.output, args.tag)
    url = f"https://github.com/{REPOSITORY}/releases/download/{args.tag}/{asset.name}"
    (args.output / "codex-mx-bridge.rb").write_text(formula(url, checksum(asset)))
    files = {path.name: checksum(path) for path in (asset, packed)}
    (args.output / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in files.items()))
    (args.output / "release.json").write_text(json.dumps(
        dict(schema_version=1, tag=args.tag, version=__version__, repository=REPOSITORY, assets=files), indent=2) + "\n")
    print(f"Built and verified {args.tag}: {asset}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("build")
    command.add_argument("--tag", required=True)
    command.add_argument("--output", type=Path, default=ROOT / "dist")
    command.add_argument("--tool-dir", type=Path, default=ROOT / ".tools/logi-release")
    args = parser.parse_args(argv)
    try:
        build(args)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
