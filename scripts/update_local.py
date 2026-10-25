#!/usr/bin/env python3.15
"""Upgrade an existing bridge installation from the current source checkout."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from mxbridge.focus import bind, make_binding, read_bindings, socket_path
from mxbridge.state import Store, default_dir
from scripts.install_local import InstallError, parse_args as installer_args, perform as install

SERVICE_APP = Path("/Applications/Utilities/LogiPluginService.app")
SERVICE_NAME = "LogiPluginService"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "codex-mx-bridge")
    parser.add_argument("--python", help="Runtime selected by update.sh")
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-downloads", action="store_true")
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument("--bind-herdr", type=Path, metavar="SOCKET")
    parser.add_argument("--iterm-id")
    parser.add_argument("--state-dir", type=Path, default=default_dir())
    return parser.parse_args(argv)


def read_installation(prefix):
    path = prefix / "installation.json"
    try:
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
    except FileNotFoundError as exc:
        raise InstallError("Existing installation not found; run bash install.sh first") from exc
    if len(raw) > 1024 * 1024:
        raise InstallError("Installation manifest exceeds 1 MiB")
    value = json.loads(raw)
    if (not isinstance(value, dict) or type(value.get("hooks_only")) is not bool or
            not isinstance(value.get("codex_home"), str) or not Path(value["codex_home"]).is_absolute()):
        raise InstallError("Invalid installation manifest; existing files were kept")
    return value


def choose_sdk(prefix, manifest, override=None):
    if override is not None:
        path = override.expanduser().resolve()
        if not path.is_file():
            raise InstallError("--sdk must name an existing PluginApi.dll")
        return path
    candidates = []
    if isinstance(manifest.get("sdk"), str):
        candidates.append(Path(manifest["sdk"]).expanduser())
    # The service can use .NET 10 while this project targets .NET 8. Prefer the
    # separately installed official tooling SDK, not the newer host assembly.
    cached = list((prefix / "tools/logiplugin/.store/logiplugintool").glob(
        "*/logiplugintool/*/tools/net8.0/any/PluginApi.dll"))
    cached += list((Path.home() / ".nuget/packages/logiplugintool").glob(
        "*/tools/net8.0/any/PluginApi.dll"))
    candidates += sorted(cached, key=lambda p: tuple(
        int(n) for n in re.findall(r"\d+", p.parents[3].name)), reverse=True)
    candidates.append(SERVICE_APP / "Contents/MonoBundle/PluginApi.dll")
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise InstallError("No SDK found; supply --sdk with a .NET 8 compatible PluginApi.dll")


def restart_service(app=SERVICE_APP, *, runner=subprocess.run, now=time.monotonic,
                    sleep=time.sleep, uid=None):
    uid = os.getuid() if uid is None else uid
    match = ["-x", "-u", str(uid), SERVICE_NAME]

    def pids():
        result = runner(["/usr/bin/pgrep", *match], capture_output=True, text=True, timeout=5)
        if result.returncode not in (0, 1):
            raise InstallError("Cannot inspect Logi Plugin Service")
        return {int(pid) for pid in result.stdout.split()} if result.returncode == 0 else set()

    previous = pids()
    if previous:
        result = runner(["/usr/bin/pkill", "-TERM", *match], capture_output=True, text=True, timeout=5)
        if result.returncode not in (0, 1):
            raise InstallError("Cannot stop Logi Plugin Service")
        deadline = now() + 10
        while pids() & previous:
            if now() >= deadline:
                raise InstallError("Logi Plugin Service did not stop; reload it manually")
            sleep(0.2)
    runner(["/usr/bin/open", "-g", "-a", str(app)], check=True, timeout=10)
    deadline = now() + 10
    while not pids():
        if now() >= deadline:
            raise InstallError("Logi Plugin Service did not start; open it manually")
        sleep(0.2)
    print("Logi Plugin Service restarted.")


def perform(args, *, root=ROOT, platform=None, runner=subprocess.run, installer=install,
            reloader=restart_service, service_app=SERVICE_APP, env=None):
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    if platform not in {"darwin", "linux"}:
        raise InstallError("Run the updater on macOS or Linux")
    prefix = args.prefix.expanduser().resolve()
    if prefix in {Path(prefix.anchor), Path.home().resolve(), root.resolve()} or prefix in root.resolve().parents:
        raise InstallError("Choose the dedicated bridge install directory, not a home/source/system root")
    manifest = read_installation(prefix)
    hooks_only = manifest["hooks_only"] or platform == "linux"
    if args.iterm_id is not None and args.bind_herdr is None:
        raise InstallError("--iterm-id requires --bind-herdr")
    binding = None
    if args.bind_herdr is not None:
        if platform != "darwin" or hooks_only:
            raise InstallError("Herdr terminal bindings belong on the Mac plugin installation")
        binding = make_binding(args.bind_herdr.expanduser(), args.iterm_id, env)
        existing = read_bindings(args.state_dir.expanduser())
        if (len(existing["bindings"]) >= 16 and
                binding["socket_path"] not in {socket_path(b["socket_path"]) for b in existing["bindings"]}):
            raise InstallError("At most 16 Herdr sessions can be bound")
    sdk = None if hooks_only else choose_sdk(prefix, manifest, args.sdk)
    if not hooks_only and not args.no_restart and not service_app.is_dir():
        raise InstallError("Logi Plugin Service is missing; install Options+ or use --no-restart")

    options = ["--prefix", str(prefix), "--codex-home", manifest["codex_home"]]
    if hooks_only:
        options.append("--hooks-only")
    else:
        options += ["--sdk", str(sdk)]
    if args.no_downloads:
        options.append("--no-downloads")
    if args.dry_run:
        options.append("--dry-run")
    print(f"Upgrade source: {root}")
    if sdk is not None:
        print(f"Build SDK: {sdk}")
    if args.dry_run:
        installer(installer_args(options), root=root, platform=platform, runner=runner, next_steps=False)
        if binding:
            print(f"Plan: bind Herdr socket {binding['socket_path']} to the selected outer iTerm2 pane.")
        if not hooks_only and not args.no_restart:
            print("Plan: restart Logi Plugin Service after the upgrade succeeds.")
        return 0

    backup = prefix / f"installation.json.mx-backup-{time.time_ns()}"
    shutil.copy2(prefix / "installation.json", backup)
    installer(installer_args(options), root=root, platform=platform, runner=runner, next_steps=False)
    if binding:
        directory = Store(args.state_dir.expanduser()).directory
        bind(directory, binding["socket_path"], binding["iterm_id"])
        print("Herdr terminal binding saved. Keep this iTerm2 pane attached to that Herdr session.")
    print(f"Upgrade installed. Previous installation manifest: {backup}")
    if not hooks_only and not args.no_restart:
        try:
            reloader(service_app, runner=runner)
        except (OSError, ValueError, InstallError, subprocess.SubprocessError) as exc:
            raise InstallError(f"Files upgraded, but the service reload failed: {exc}") from exc
    elif not hooks_only:
        print("Plugin reload deferred; restart Logi Plugin Service to load the new build.")
    print("Review the updated Codex hooks in /hooks; restart/resume Codex if it still uses the old hook path.")
    return 0


def main(argv=None):
    try:
        return perform(parse_args(argv))
    except (OSError, ValueError, InstallError, subprocess.SubprocessError) as exc:
        print(f"Upgrade stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if sys.version_info[:2] != (3, 15) or sys.version_info.releaselevel != "final":
        print("Python 3.15 is required; run bash update.sh.", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main())
