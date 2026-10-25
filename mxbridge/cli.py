import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from .install import definition, install
from .install import record_target, require_cli, target, validate_kiro_profile
from .adapters import CLIENTS, LABELS
from .adapters.common import identity
from .ssh import collect_once, command
from .state import Store, apply_event, export_snapshot, run_start, run_update

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def hook_deadline():
    """Finish before the host's 2s timeout, even if stdin never closes."""
    if not hasattr(signal, "setitimer"):
        yield
        return
    previous = signal.getsignal(signal.SIGALRM)
    def expired(_signum, _frame):
        raise TimeoutError("Hook deadline exceeded")
    signal.signal(signal.SIGALRM, expired)
    timer = signal.setitimer(signal.ITIMER_REAL, 1.0)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if timer != (0.0, 0.0):
            signal.setitimer(signal.ITIMER_REAL, *timer)


def hook(store, client="codex", instance=""):
    # Hooks always succeed silently. Stop/SubagentStop get valid JSON, never prose.
    try:
        raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Oversize hook payload")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Hook input must be an object")
        with store.transaction() as state:
            apply_event(state, payload, client=client, instance=instance)
    except Exception:
        # Do not disclose prompts, tool args, or transcript content on error.
        try:
            name = "hook-error.txt" if client == "codex" else f"hook-{client}-error.txt"
            (store.directory / name).write_text(
                "Bridge hook failed; inspect directory permissions, lock, and state.json.\n",
                encoding="utf-8")
        except OSError:
            pass
    if client == "codex":
        print("{}")
    return 0


def launch(store, argv, label, client="codex", instance=""):
    identity(instance, optional=True, limit=80)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        argv = ["kiro-cli" if client == "kiro" else client]
    env = dict(os.environ, MX_CODEX_RUN_ID=str(uuid.uuid4()),
               MX_CODEX_STATE_DIR=str(store.directory.resolve()),
               MX_BRIDGE_CLIENT=client, MX_BRIDGE_INSTANCE=instance)
    if label:
        env["MX_CODEX_LABEL"] = label
    try:
        env["MX_CODEX_TTY"] = os.ttyname(0)
    except (OSError, AttributeError):
        pass
    rid = env["MX_CODEX_RUN_ID"]
    with store.transaction() as state:
        run_start(state, rid, label or Path.cwd().name, env, time.time(), client, instance)
    child = None
    old_handlers = {}
    try:
        child = subprocess.Popen(argv, env=env)  # inherit all three terminal streams
        if os.name == "posix":
            # SIGINT reaches Codex directly via the terminal process group.
            old_handlers[signal.SIGINT] = signal.signal(signal.SIGINT, lambda *_: None)
            # Forward non-terminal termination to the child; still wait/reap it.
            for sig in (signal.SIGTERM, signal.SIGHUP):
                old_handlers[sig] = signal.signal(sig, lambda s, _f: child.send_signal(s))
        while child.poll() is None:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    with store.transaction() as state:
                        run_update(state, rid, time.time())
                except (OSError, ValueError, TimeoutError):
                    pass  # a display failure must not kill Codex
        code = child.returncode
    except OSError as exc:
        print(f"Cannot start agent: {exc}", file=sys.stderr)
        code = 127
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    try:
        with store.transaction() as state:
            run_update(state, rid, time.time(), code)
    except (OSError, ValueError, TimeoutError):
        pass
    return code if code >= 0 else 128 - code


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent command hooks to Logi Actions SDK bridge")
    parser.add_argument("--state-dir", type=Path, help="Override state directory")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("hook", help="Observational command hook, JSON on stdin")
    p.add_argument("--client", choices=CLIENTS, default="codex")
    p.add_argument("--instance", default="")
    p.add_argument("--hook-owner", help=argparse.SUPPRESS)
    sub.add_parser("export", help="Emit local-only sanitized snapshot for SSH")
    sub.add_parser("status", help="Inspect raw bridge state")
    p = sub.add_parser("install-hooks", help="Preview or merge hooks; preserves Herdr")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--remove", action="store_true")
    p.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home()/".codex")))
    p.add_argument("--client", choices=CLIENTS, default="codex")
    p.add_argument("--claude-settings", type=Path)
    p.add_argument("--agent-config", type=Path)
    p.add_argument("--kiro-format", choices=("v2", "v3"), default="v2",
                   help="Kiro profile hook shape; v2 object or v3 inline array")
    p.add_argument("--instance", default="")
    p = sub.add_parser("run", help="Optional process heartbeat and exit tracking")
    p.add_argument("--label")
    p.add_argument("--client", choices=CLIENTS, default="codex")
    p.add_argument("--instance", default="")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("collect-ssh", help="Collect Linux status over existing SSH trust")
    p.add_argument("--host", required=True, help="SSH config alias")
    p.add_argument("--alias", required=True, help="Unique display/source label")
    p.add_argument("--remote-script", required=True, help="Absolute Linux bridge.py path")
    p.add_argument("--remote-python", default="python3.15")
    p.add_argument("--remote-state")
    p.add_argument("--interval", type=float, default=3)
    p.add_argument("--once", action="store_true")
    p = sub.add_parser("clear", help="Remove historical local rows, or one remote source")
    p.add_argument("--remote")
    p = sub.add_parser("herdr-focus", help="Bind local Herdr sessions to their outer iTerm2 panes")
    focus = p.add_subparsers(dest="focus_action", required=True)
    focus.add_parser("list", help="Show configured terminal bindings")
    p = focus.add_parser("bind", help="Register the outer iTerm2 pane for a local Herdr socket")
    p.add_argument("--socket", type=Path, required=True)
    p.add_argument("--iterm-id", help="Explicit outer iTerm2 ID; otherwise use this shell's ID")
    p = focus.add_parser("remove", help="Disable focus for one Herdr socket")
    p.add_argument("--socket", type=Path, required=True)
    p = sub.add_parser("demo", help="Write an isolated synthetic snapshot")
    p = sub.add_parser("display", help="Inspect/change local button theme; no restart needed")
    p.add_argument("--mode", choices=("text", "pet"))
    p.add_argument("--pet", help="Imported name or full revision ID")
    p.add_argument("--fps", type=int, choices=range(1,9))
    p.add_argument("--motion", choices=("on", "off"))
    for flag in ("show-name", "show-location", "show-client", "show-status", "use-chat-names"):
        p.add_argument("--" + flag, choices=("on", "off"))
    p = sub.add_parser("pet", help="Local sprite-sheet assets for this bridge")
    pets = p.add_subparsers(dest="pet_action", required=True)
    pets.add_parser("list")
    p = pets.add_parser("import")
    p.add_argument("--sheet", type=Path, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--layout", type=Path, help="Explicit atlas layout for another sprite version")
    args = parser.parse_args(argv)
    if args.action == "install-hooks":
        try:
            selected = target(args.client, codex_home=args.codex_home,
                              claude_settings=args.claude_settings, agent_config=args.agent_config,
                              kiro_format=args.kiro_format, instance=args.instance,
                              require_existing=not args.remove)
            options = dict(client=args.client, kiro_format=args.kiro_format)
            proposed = {} if args.remove else definition(
                ROOT / "bridge.py", instance=args.instance, **options)
            result = install(selected["path"], proposed, **options)
            if args.apply:
                record_target(ROOT/"bridge.py", selected, remove=args.remove, apply=False)
                if not args.remove:
                    executable = require_cli(args.client)
                    if args.client == "kiro":
                        validate_kiro_profile(result, executable, cwd=Path(selected["path"]).parent)
                result = install(selected["path"], proposed, True, **options)
                record_target(ROOT/"bridge.py", selected, remove=args.remove)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2))
        if args.apply and not args.remove:
            if args.client == "codex":
                print("Merged. Restart Codex, then review and trust entries in /hooks.", file=sys.stderr)
            else:
                print(f"Merged {LABELS[args.client]} hooks. Start a new session using this configuration.",
                      file=sys.stderr)
        return 0
    if args.action == "hook":
        try:
            with hook_deadline():
                return hook(Store(args.state_dir), args.client, args.instance)
        except Exception:
            if args.client == "codex":
                print("{}")
            return 0
    store = Store(args.state_dir)
    if args.action == "herdr-focus":
        from . import focus
        try:
            if args.focus_action == "bind":
                result = focus.bind(store.directory, args.socket.expanduser(), args.iterm_id)
            elif args.focus_action == "remove":
                result = focus.remove(store.directory, args.socket.expanduser())
            else:
                result = focus.read_bindings(store.directory)
            print(json.dumps(result, indent=2))
            return 0
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if args.action in {"display", "pet"}:
        from . import pets
        try:
            if args.action == "display":
                labels = {key: None if getattr(args, key) is None else getattr(args, key) == "on"
                          for key in ("show_name", "show_location", "show_client", "show_status", "use_chat_names")}
                if any(v is not None for v in (args.mode, args.pet, args.fps, args.motion, *labels.values())):
                    result = pets.configure(store.directory, mode=args.mode, pet=args.pet, fps=args.fps,
                                            motion=args.motion, **labels)
                else:
                    result = pets.read_display(store.directory)
            elif args.pet_action == "list":
                result = pets.list_pets(store.directory)
            else:
                result = dict(pet=pets.import_pet(store.directory, args.sheet, args.name, args.layout))
            print(json.dumps(result, indent=2))
            return 0
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    if args.action == "run":
        return launch(store, args.command, args.label, args.client, args.instance)
    if args.action == "export":
        print(json.dumps(export_snapshot(store.read())))
    elif args.action == "status":
        print(json.dumps(store.read(), indent=2))
    elif args.action == "collect-ssh":
        if args.interval < 1 or args.interval > 60:
            parser.error("--interval must be between 1 and 60 seconds")
        cmd = command(args.host, args.remote_script, args.remote_python, args.remote_state)
        while True:
            ok = collect_once(store, args.alias, cmd)
            if args.once:
                return 0 if ok else 1
            if not ok:
                print(f"{args.alias}: connection failed; cached rows marked OFFLINE", file=sys.stderr)
            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                return 0
    elif args.action == "clear":
        with store.transaction() as state:
            if args.remote:
                state["remotes"].pop(args.remote, None)
            else:
                state["rows"] = [r for r in state["rows"] if
                    r["status"] not in {"CLOSED", "EXIT ERROR", "STOPPED"} and
                    time.time() <= r["valid_until"]]
    elif args.action == "demo":
        if args.state_dir is None:
            parser.error("demo requires --state-dir pointing to a separate test directory")
        with store.transaction() as state:
            for i, event in enumerate(("UserPromptSubmit", "PermissionRequest", "Stop")):
                payload = dict(session_id=f"demo-{i}", cwd=f"/demo/project-{i}",
                               hook_event_name=event, turn_id="demo-turn")
                apply_event(state, payload, env={})
    return 0
