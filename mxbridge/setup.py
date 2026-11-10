"""Activate a Homebrew distribution using the existing conservative installer."""
import json
from pathlib import Path
import subprocess
import sys

from .distribution import validate_plugin
from .install import targets_from_manifest
from .settings_launch import install_app
from scripts import install_local
from scripts.update_local import restart_service

ROOT = Path(__file__).resolve().parent.parent


def perform(args, *, root=ROOT, platform=None, installer=install_local.perform,
            reloader=restart_service, runner=subprocess.run):
    platform = platform or sys.platform
    record = root / "homebrew.json"
    if not record.is_file():
        raise ValueError("Run setup from a Homebrew installation; source checkouts use bash install.sh")
    value = json.loads(record.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema_version") != 1 or
            not isinstance(value.get("python"), str) or not Path(value["python"]).is_absolute()):
        raise ValueError("Invalid Homebrew runtime record; reinstall the formula")
    python = Path(value["python"])
    if not python.is_file():
        raise ValueError("Homebrew Python is missing; run brew reinstall python@3.15")
    args.managed_python = python
    args.prebuilt_plugin = validate_plugin(root)
    hooks_only = args.hooks_only or platform == "linux"
    args.with_pets = not hooks_only
    manifest = args.prefix.expanduser() / "installation.json"
    remembered = targets_from_manifest(json.loads(manifest.read_text())) if manifest.is_file() else None
    # Preserve registered client scopes on upgrades; initial Kiro scopes are explicit.
    explicit = (getattr(args, "scopes_explicit", False) or args.clients or args.agent_config or
                args.claude_settings or args.pi_agent_dir)
    if args.agent_config and not args.clients:
        args.clients = ["kiro"]
    if args.claude_settings and not args.clients:
        args.clients = ["claude"]
    if args.pi_agent_dir and not args.clients:
        args.clients = ["pi"]
    selected = remembered if remembered and not explicit else None
    if not args.dry_run and manifest.is_file():
        from .settings import private_write
        import time
        private_write(manifest.with_name(manifest.name + f".mx-backup-{time.time_ns()}"), manifest.read_bytes())
    installer(args, root=root, platform=platform, runner=runner, hook_targets=selected)
    if args.dry_run:
        if platform == "darwin" and not hooks_only:
            print("Plan: install the Finder launcher and reload Logi Plugin Service.")
        return 0
    if platform == "darwin" and not hooks_only:
        command = args.prefix.expanduser().resolve() / "bin/codex-mx"
        app = install_app([str(command), "settings"])
        print(f"Settings app: {app}")
        if not args.no_restart:
            reloader(runner=runner)
    print("Setup complete. Run codex-mx settings to edit display settings and pets.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    record = ROOT / "homebrew.json"
    if record.is_file():
        try:
            installed = json.loads(record.read_text())
            current = Path(installed["root"])
            python = Path(installed["python"])
            if not current.is_absolute() or not python.is_absolute():
                raise ValueError("Homebrew paths must be absolute")
            if current.resolve() != ROOT.resolve():
                if not (current / "bridge.py").is_file():
                    raise ValueError("The Homebrew formula is missing; reinstall codex-mx-bridge before setup")
                return subprocess.run([str(python), str(current / "bridge.py"), "setup", *argv]).returncode
        except (OSError, KeyError, ValueError, TypeError) as exc:
            print(f"Cannot locate the current Homebrew installation: {exc}", file=sys.stderr)
            return 1
    parser = install_local.make_parser()
    parser.description = "Activate the Homebrew bridge, selected agent hooks, settings app, and prebuilt Logitech plugin"
    parser.add_argument("--no-restart", action="store_true", help="Defer the Logitech service restart")
    args = parser.parse_args(argv)
    scopes = {"--client", "--codex-home", "--claude-settings", "--agent-config",
              "--pi-agent-dir", "--instance", "--kiro-format"}
    args.scopes_explicit = any(arg.split("=", 1)[0] in scopes for arg in argv)
    try:
        return perform(args)
    except (ValueError, OSError, install_local.InstallError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
