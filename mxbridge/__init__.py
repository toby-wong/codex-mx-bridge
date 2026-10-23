"""Codex MX bridge, schema v1."""
import sys

if sys.version_info[:2] != (3, 15) or sys.version_info.releaselevel != "final":
    raise RuntimeError("Codex MX Bridge requires a stable Python 3.15 interpreter")

__version__ = "0.2.0"
