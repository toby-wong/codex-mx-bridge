#!/usr/bin/env python3.15
"""Portable tests plus Python -> C# wire compatibility, no hardware required."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mxbridge.focus import bind, bind_remote
from mxbridge.pets import DEFAULT_DISPLAY, validate_display
from mxbridge.state import Store, apply_event, export_snapshot
from mxbridge.ssh import decode

subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, check=True)
with tempfile.TemporaryDirectory(prefix="mx-contract-") as state:
    subprocess.run([sys.executable, "bridge.py", "--state-dir", state, "demo"], cwd=ROOT, check=True)
    with Store(state).transaction() as wire:
        apply_event(wire, dict(session_id="herdr-contract", hook_event_name="SessionStart"),
                    env=dict(HERDR_ENV="1", HERDR_SOCKET_PATH="/tmp/mx-herdr.sock"))
        apply_event(wire, dict(session_id="client-contract", hook_event_name="StopFailure"),
                    env={}, client="claude")
        apply_event(wire, dict(session_id="client-contract", hook_event_name="preToolUse"),
                    env={}, client="kiro")
        exported = export_snapshot(wire, 100)
        exported["rows"] = [row for row in exported["rows"] if row["session_id"] == "herdr-contract"]
        # Decoder must strip even injected local control fields.
        exported["rows"][0].update(herdr_socket="/tmp/injected.sock", iterm_id="untrusted", tty="/dev/tty0")
        wire["remotes"]["remote-contract"] = dict(rows=decode(json.dumps(exported), 100), received_at=100, error="")
    bind(state, "/tmp/mx-herdr.sock", "12345678-1234-1234-1234-123456789abc")
    bind_remote(state, "remote-contract", "87654321-4321-4321-4321-cba987654321",
                ssh_target="workbox", herdr_path="/home/user/.local/bin/herdr", remote_session="work")
    (Path(state)/"pet-display.json").write_text(json.dumps(validate_display(dict(
        DEFAULT_DISPLAY, mode="pet", pet="clippit", pet_rules=[
            dict(location="remote", pet="pingu"),
            dict(location="remote", client="claude", pet="leader-avatar/0123456789abcdef")]))))
    subprocess.run(["dotnet", "run", "--project", "tests/ViewModelTests", "--", str(Path(state)/"state.json")], cwd=ROOT, check=True)
