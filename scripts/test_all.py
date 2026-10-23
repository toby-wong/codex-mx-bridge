#!/usr/bin/env python3.15
"""Portable tests plus Python -> C# wire compatibility, no hardware required."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, check=True)
with tempfile.TemporaryDirectory(prefix="mx-contract-") as state:
    subprocess.run([sys.executable, "bridge.py", "--state-dir", state, "demo"], cwd=ROOT, check=True)
    subprocess.run(["dotnet", "run", "--project", "tests/ViewModelTests", "--", str(Path(state)/"state.json")], cwd=ROOT, check=True)
