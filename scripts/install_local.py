#!/usr/bin/env python3.15
"""Idempotent local Mac install; --hooks-only installs the Linux export side."""
import argparse
import hashlib
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
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from mxbridge import __version__
from mxbridge.install import definition, install
from mxbridge.state import atomic_json

ITEMS = ("bridge.py", "mxbridge", "plugin", "scripts", "tests", "docs", "README.md",
         "global.json", "pyproject.toml", ".python-version", "install.sh", "update.sh")
EXCLUDED = {"bin", "obj", ".git", ".tools", "__pycache__"}


class InstallError(RuntimeError):
    pass


def source_files(root):
    paths = []
    for name in ITEMS:
        path = root / name
        if path.is_file():
            paths.append(path)
        elif path.is_dir():
            paths.extend(p for p in path.rglob("*") if p.is_file() and
                         not set(p.relative_to(path).parts) & EXCLUDED and p.suffix != ".pyc")
    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def stage_source(root, prefix):
    files = source_files(root)
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.relative_to(root).as_posix().encode() + b"\0" + file.read_bytes())
    target = prefix / "releases" / (__version__ + "-" + digest.hexdigest()[:12])
    if target.exists():
        if not all((target/f.relative_to(root)).is_file() and
                   (target/f.relative_to(root)).read_bytes() == f.read_bytes() for f in files):
            raise InstallError("Installed release was modified; keep it for diagnosis and use a new prefix")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=target.parent) as folder:
        staged = Path(folder)/"release"
        for file in files:
            dest = staged/file.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dest)
        staged.rename(target)
    return target


def hooks_enabled_text(text):
    """Preserve TOML text; accept edits only if its parsed meaning is exact."""
    before = tomllib.loads(text)
    features = before.get("features", {})
    if not isinstance(features, dict):
        raise InstallError("config.toml features must be a table")
    disabled = features.get("hooks", features.get("codex_hooks")) is False
    if not disabled:
        return text
    desired = dict(before, features=dict(features, hooks=True))
    candidates = []
    if features.get("hooks") is False:
        # Also supports quoted keys, inline tables and dotted assignments.
        for match in re.finditer(r"\bfalse\b", text):
            candidates.append(text[:match.start()] + "true" + text[match.end():])
    else:
        candidates.extend(("features.hooks = true\n" + text, text + "\n[features]\nhooks = true\n"))
        offset = 0
        for line in text.splitlines(keepends=True):
            offset += len(line)
            candidates.append(text[:offset] + "\nhooks = true\n" + text[offset:])
        for match in re.finditer(r"\{", text):
            candidates.append(text[:match.end()] + " hooks = true," + text[match.end():])
    for candidate in candidates:
        try:
            if tomllib.loads(candidate) == desired:
                return candidate
        except tomllib.TOMLDecodeError:
            pass
    raise InstallError("Cannot safely enable hooks in this TOML layout; no config was changed")


def enable_hooks(path):
    if not path.exists():
        return
    before = path.read_bytes()
    after = hooks_enabled_text(before.decode("utf-8"))
    if after.encode("utf-8") == before:
        return
    if path.read_bytes() != before:
        raise InstallError("config.toml changed during installation; retry")
    shutil.copy2(path, path.with_name(path.name + f".mx-backup-{time.time_ns()}"))
    fd, tmp = tempfile.mkstemp(prefix=".mx-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(after)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prefix", type=Path, default=Path(os.environ.get("XDG_DATA_HOME", Path.home()/".local/share"))/"codex-mx-bridge")
    p.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home()/".codex")))
    p.add_argument("--python", help="Interpreter selected by install.sh")
    p.add_argument("--hooks-only", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Plan only; no downloads or install changes")
    p.add_argument("--no-downloads", action="store_true")
    p.add_argument("--install-options", action="store_true")
    p.add_argument("--with-pets", action="store_true", help="Install optional Pillow 13 sprite importer (Mac only)")
    p.add_argument("--pet-sheet", type=Path, help="Import and enable this local pet atlas; implies --with-pets")
    p.add_argument("--pet-name", default="codex-pet")
    p.add_argument("--pet-layout", type=Path, help="Explicit layout JSON for a different sprite-sheet version")
    p.add_argument("--motion", choices=("on", "off"))
    p.add_argument("--sdk", type=Path, default=Path("/Applications/Utilities/LogiPluginService.app/Contents/MonoBundle/PluginApi.dll"))
    return p.parse_args(argv)


def get_dotnet(prefix, no_downloads, runner=subprocess.run):
    local = prefix/"tools/dotnet/dotnet"
    for executable in (str(local), shutil.which("dotnet")):
        if not executable or not Path(executable).is_file():
            continue
        result = runner([executable, "--list-sdks"], capture_output=True, text=True, check=True)
        if any(int(patch) >= 200 for patch in re.findall(r"^8\.0\.(\d+)\s", result.stdout, re.M)):
            return executable
    if no_downloads:
        raise InstallError("A .NET 8 SDK (8.0.200+) is needed to build the plugin; downloads are disabled")
    local.parent.mkdir(parents=True, exist_ok=True)
    script = prefix/"tools/dotnet-install.sh"
    with urllib.request.urlopen("https://dot.net/v1/dotnet-install.sh", timeout=30) as response:
        script.write_bytes(response.read(1024*1024))
    runner(["bash", str(script), "--channel", "8.0", "--quality", "GA", "--install-dir", str(local.parent), "--no-path"], check=True)
    if not local.is_file():
        raise InstallError(".NET installer did not create the expected executable")
    return str(local)


def back_up_packaged_plugins(plugins, prefix):
    for name in ("CodexMx", "CodexMxPlugin"):
        packaged = plugins/name
        if not packaged.exists():
            continue
        metadata = packaged/"metadata/LoupedeckPackage.yaml"
        text = metadata.read_text(encoding="utf-8") if metadata.is_file() else ""
        if (packaged.is_symlink() or not re.search(r"(?m)^name:\s*CodexMx\s*$", text) or
                not re.search(r"(?m)^pluginFileName:\s*CodexMxPlugin\.dll\s*$", text)):
            raise InstallError(f"Unrecognized existing plugin directory: {packaged}; kept unchanged")
        backups = prefix/"backups"
        backups.mkdir(exist_ok=True)
        # Only move these explicitly named, verified bridge package directories.
        backup = backups/(name+f"-{time.time_ns()}")
        shutil.move(str(packaged), str(backup))
        print(f"Previous bridge package backed up to {backup}")


def perform(args, *, root=ROOT, platform=None, runner=subprocess.run, which=shutil.which, next_steps=True):
    platform = sys.platform if platform is None else platform
    if platform not in {"darwin", "linux"}:
        raise InstallError("Run the installer on macOS or Linux")
    hooks_only = args.hooks_only or platform == "linux"
    with_pets = args.with_pets or args.pet_sheet is not None
    if hooks_only and (with_pets or args.motion is not None):
        raise InstallError("Pet assets/display belong on the Mac; Linux needs only hooks/export")
    if args.pet_sheet and (not args.pet_sheet.expanduser().is_file() or
                           not 0 < args.pet_sheet.expanduser().stat().st_size <= 20*1024*1024):
        raise InstallError("--pet-sheet must name an existing PNG/WebP atlas up to 20 MiB")
    prefix = args.prefix.expanduser().resolve()
    codex_home = args.codex_home.expanduser().resolve()
    if prefix in {Path(prefix.anchor), Path.home().resolve()} or prefix == root or prefix in root.parents:
        raise InstallError("Choose a dedicated install directory, not a home/source/system root")
    print(f"Python: {sys.version.split()[0]}")
    print(f"Install directory: {prefix}")
    print(f"Codex config: {codex_home}")
    print("Mode: hooks/export only" if hooks_only else "Mode: Mac hooks and Logitech plugin")
    config = codex_home/"config.toml"
    if config.exists():
        hooks_enabled_text(config.read_text(encoding="utf-8"))
    hooks = codex_home/"hooks.json"
    # Validate existing definitions before installing dependencies or touching files.
    install(hooks, definition(root/"bridge.py"), apply=False)
    if args.dry_run:
        print("Plan: stage source; create Python 3.15 venv; self-check; back up/merge hooks; enable hooks if disabled; write launcher.")
        if not hooks_only:
            print("Plan: locate Options+ SDK; obtain .NET 8 if needed; build plugin; back up/write development link.")
        if with_pets:
            print("Plan: install optional Pillow 13; import/enable the supplied local sheet if specified.")
        print("No changes made. Hook trust and device assignments remain manual.")
        return 0
    if not which("codex"):
        raise InstallError("Codex CLI is missing from PATH; install it first, then rerun")
    if not hooks_only and not args.sdk.expanduser().is_file():
        if args.install_options and which("brew") and not args.no_downloads:
            runner([which("brew"), "install", "--cask", "logi-options+"], check=True)
        if not args.sdk.expanduser().is_file():
            raise InstallError("Logi Options+ SDK is missing. Install Options+ and finish its setup, or use --install-options with Homebrew; then rerun. https://www.logitech.com/software/logi-options-plus.html")
    prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(prefix, 0o700)
    release = stage_source(root, prefix)
    venv = prefix/"venv-3.15"
    python = venv/("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        runner([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    runner([str(python), "-c", "import sys; assert sys.version_info[:2] == (3,15) and sys.version_info.releaselevel == 'final'"], check=True)
    pet_id = None
    if with_pets:
        check = runner([str(python), "-c", "import PIL; assert PIL.__version__ == '13.0.0'"], capture_output=True, check=False)
        if check.returncode:
            if args.no_downloads:
                raise InstallError("Pillow 13.0.0 is missing from the installed venv; --no-downloads prevents installing it")
            runner([str(python), "-m", "ensurepip", "--upgrade"], check=True)
            runner([str(python), "-m", "pip", "install", "--only-binary=:all:", "Pillow==13.0.0"], check=True)
        if args.pet_sheet:
            cmd = [str(python), str(release/"bridge.py"), "pet", "import", "--sheet", str(args.pet_sheet.expanduser().resolve()), "--name", args.pet_name]
            if args.pet_layout:
                cmd += ["--layout", str(args.pet_layout.expanduser().resolve())]
            try:
                result = runner(cmd, capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError as exc:
                raise InstallError("Pet import failed: " + str(exc.stderr or exc)[-1500:]) from exc
            pet_id = json.loads(result.stdout)["pet"]
    # Use a separate state directory, never overwrite existing live agent rows.
    with tempfile.TemporaryDirectory(prefix="mx-install-check-") as folder:
        payload = json.dumps(dict(session_id="install-check", hook_event_name="SessionStart", cwd="/install/check"))
        result = runner([str(python), str(release/"bridge.py"), "--state-dir", folder, "hook"],
                        input=payload, capture_output=True, text=True, check=True)
        state_file = Path(folder)/"state.json"
        if result.stdout.strip() != "{}" or not state_file.is_file() or json.loads(state_file.read_text())["rows"][0]["session_id"] != "install-check":
            raise InstallError("Installed hook self-check failed; live hooks were not changed")
    plugin_link = None
    if not hooks_only:
        dotnet = get_dotnet(prefix, args.no_downloads, runner)
        env = dict(os.environ, PATH=str(Path(dotnet).parent)+os.pathsep+os.environ.get("PATH", ""))
        if Path(dotnet).parent == prefix/"tools/dotnet":
            env["DOTNET_ROOT"] = str(Path(dotnet).parent)
        runner([dotnet, "build", str(release/"plugin/CodexMxPlugin.csproj"), "-c", "Release",
                "-p:PluginApiPath="+str(args.sdk.expanduser().resolve())], cwd=release, env=env, check=True)
        package = release/"plugin/bin/Release/package"
        if not (package/"bin/CodexMxPlugin.dll").is_file():
            raise InstallError("Plugin build output missing; live hooks were not changed")
        plugins = Path.home()/"Library/Application Support/Logi/LogiPluginService/Plugins"
        # Avoid a packaged plugin and development link loading the same assembly twice.
        back_up_packaged_plugins(plugins, prefix)
        plugins.mkdir(parents=True, exist_ok=True)
        plugin_link = plugins/"CodexMxPlugin.link"
        if plugin_link.exists() and plugin_link.read_text().strip() != str(package):
            shutil.copy2(plugin_link, plugin_link.with_name(plugin_link.name+f".mx-backup-{time.time_ns()}"))
        plugin_link.write_text(str(package)+"\n", encoding="utf-8")
    # Apply only after runtime, self-check, and plugin build have passed.
    enable_hooks(config)
    install(hooks, definition(release/"bridge.py", str(python)), apply=True)
    if pet_id is not None or args.motion is not None:
        cmd = [str(python), str(release/"bridge.py"), "display"]
        if pet_id is not None:
            cmd += ["--mode", "pet", "--pet", pet_id]
        if args.motion is not None:
            cmd += ["--motion", args.motion]
        runner(cmd, check=True)
    bin_dir = prefix/"bin"
    bin_dir.mkdir(exist_ok=True)
    launcher = bin_dir/"codex-mx"
    launcher.write_text("#!/bin/sh\nexec "+shlex.join([str(python), str(release/"bridge.py")])+ ' "$@"\n', encoding="utf-8")
    launcher.chmod(0o700)
    atomic_json(prefix/"installation.json", dict(version=__version__, python=str(python),
        release=str(release), codex_home=str(codex_home), launcher=str(launcher),
        hooks_only=hooks_only, plugin_link=str(plugin_link) if plugin_link else None,
        plugin_release=str(release) if plugin_link else None,
        sdk=str(args.sdk.expanduser().resolve()) if not hooks_only else None))
    print("Installed and self-check passed.")
    print(f"Bridge command: {shlex.quote(str(launcher))} status")
    print(f"Remote Python path: {python}")
    print(f"Remote script path: {release/'bridge.py'}")
    if hooks_only:
        print("Mac collector arguments: "+shlex.join(["--remote-python", str(python), "--remote-script", str(release/"bridge.py")]))
    if next_steps:
        print("Restart Codex, then review and trust the bridge entries in /hooks (required by Codex).")
        if not hooks_only:
            print("Restart Logi Plugin Service in Options+, then map Agent slot 1–9 and Agent pages.")
    return 0


def main(argv=None):
    try:
        return perform(parse_args(argv))
    except (InstallError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Install stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
