#!/usr/bin/env python3.15
"""Entry point; Python 3.15, no third-party packages."""
import sys


def hook_client(argv):
    # Ignore only recognized global options, not a child command named "hook".
    index = 0
    while index < len(argv):
        if argv[index] == "--state-dir":
            index += 2
        elif argv[index].startswith("--state-dir="):
            index += 1
        else:
            break
    if index >= len(argv) or argv[index] != "hook":
        return None
    rest = argv[index+1:]
    for i, arg in enumerate(rest):
        if arg == "--client":
            return rest[i+1] if i+1 < len(rest) else "unknown"
        if arg.startswith("--client="):
            return arg.split("=", 1)[1]
    return "codex"


client = hook_client(sys.argv[1:])
if sys.version_info[:2] != (3, 15) or sys.version_info.releaselevel != "final":
    if client is not None:
        if client == "codex":
            print("{}")
        raise SystemExit(0)
    print("Python 3.15 is required. Run bash install.sh, or use python3.15.", file=sys.stderr)
    raise SystemExit(2)

if __name__ == "__main__":
    if client is not None:
        # Includes import/argument errors before the handler. Never send error
        # prose or an accidental nonzero decision back to an agent.
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                from mxbridge.cli import main
                main()
            except BaseException:
                pass
        if client == "codex":
            print("{}")
    else:
        from mxbridge.cli import main
        raise SystemExit(main())
