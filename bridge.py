#!/usr/bin/env python3.15
"""Entry point; Python 3.15, no third-party packages."""
import sys

if sys.version_info[:2] != (3, 15) or sys.version_info.releaselevel != "final":
    if "hook" in sys.argv[1:]:
        print("{}")  # Old interpreter configuration must never block Codex.
        raise SystemExit(0)
    print("Python 3.15 is required. Run bash install.sh, or use python3.15.", file=sys.stderr)
    raise SystemExit(2)

from mxbridge.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
