#!/usr/bin/env python3.15
"""Real Pi dispatch with an isolated extension directory and a provider that never connects."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mxbridge.install import definition, install, require_cli


def prepare(directory):
    agent = directory/"agent"
    extensions = agent/"extensions"
    extensions.mkdir(parents=True)
    (agent/"settings.json").write_text(json.dumps(dict(
        defaultProvider="mx-fixture", defaultModel="fixture", defaultThinkingLevel="off",
        retry=dict(enabled=False), compaction=dict(enabled=False))))
    install(extensions/"codex-mx-bridge.ts", definition(ROOT/"bridge.py", client="pi"), True, client="pi")
    shutil.copy2(ROOT/"tests/fixtures/pi-offline-provider.ts", extensions/"mx-offline-provider.ts")
    return agent


def run_case(executable, directory, agent, state_dir, name, *, session=None, child_id="", failure=False):
    session = session or directory/(name+".jsonl")
    env = dict(os.environ, PI_CODING_AGENT_DIR=str(agent), MX_CODEX_STATE_DIR=str(state_dir),
               MX_PI_SMOKE_FAILURE="1" if failure else "0")
    for key in ("PI_SUBAGENT_ID", "PI_SUBAGENT_NAME", "PI_SUBAGENT_SESSION", "PI_SUBAGENT_AGENT",
                "MX_CODEX_RUN_ID", "MX_BRIDGE_CLIENT", "MX_BRIDGE_INSTANCE", "MX_PI_SMOKE_DELEGATE", "HERDR_ENV",
                "HERDR_SOCKET_PATH", "HERDR_PANE_ID", "ITERM_SESSION_ID"):
        env.pop(key, None)
    if child_id:
        env.update(PI_SUBAGENT_ID=child_id, PI_SUBAGENT_NAME=name, PI_SUBAGENT_SESSION=str(session),
                   PI_SUBAGENT_AGENT="frontier")
    command = [executable, "--mode", "json", "--print", "--session", str(session),
               "--provider", "mx-fixture", "--model", "fixture", "--thinking", "off",
               "--no-skills", "--no-prompt-templates", "--no-themes", "Run the offline fixture."]
    states = []
    start = time.monotonic()
    with (directory/(name+".stdout")).open("w") as out, (directory/(name+".stderr")).open("w") as error:
        process = subprocess.Popen(command, env=env, cwd=directory, stdout=out, stderr=error)
        try:
            while process.poll() is None:
                if time.monotonic() - start > 30:
                    raise TimeoutError("Pi offline dispatch did not finish")
                try:
                    current = json.loads((state_dir/"state.json").read_text())
                    rows = [r for r in current["rows"] if r.get("session_path") == str(session)]
                    if rows and (not states or states[-1] != rows[0]["status"]):
                        states.append(rows[0]["status"])
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                time.sleep(0.02)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
    if process.returncode and not failure:
        raise AssertionError(f"Pi failed; inspect {directory/(name+'.stderr')}")
    current = json.loads((state_dir/"state.json").read_text())
    row = next(r for r in current["rows"] if r.get("session_path") == str(session))
    with session.open() as stream:
        native_id = json.loads(stream.readline())["id"]
    assert row["session_id"] == native_id
    assert row["client"] == "pi" and row["status"] == "CLOSED"
    assert row["last_event"] == "session_shutdown"
    assert not row["herdr"] and not row["iterm_id"], "headless Pi claimed terminal focus"
    assert row["kind"] == ("subagent" if child_id else "session")
    assert row["agent_id"] == child_id
    assert "WORKING" in states, states
    assert ("TURN ERROR" if failure else "TURN STOP") in states, states
    if not failure and name != "child-resumed":
        assert "TOOL" in states, states
    assert not (state_dir/"hook-pi-error.txt").exists()
    return dict(case=name, key=row["key"], session_id=native_id, states=states, closed=True), session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pi", default=shutil.which("pi"))
    parser.add_argument("--output", type=Path, help="Keep private test receipts in this new directory")
    args = parser.parse_args()
    if not args.pi:
        parser.error("Install Pi 1.5.0 or supply --pi")
    require_cli("pi", which=lambda _: args.pi)
    directory = args.output.expanduser().resolve() if args.output else Path(tempfile.mkdtemp(prefix="mx-pi-native-"))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        agent = prepare(directory)
        state_dir = directory/"state"
        receipts = []
        receipt, _ = run_case(args.pi, directory, agent, state_dir, "parent")
        receipts.append(receipt)
        receipt, child = run_case(args.pi, directory, agent, state_dir, "child", child_id="launch-one")
        receipts.append(receipt)
        receipt, _ = run_case(args.pi, directory, agent, state_dir, "child-resumed",
                              session=child, child_id="launch-two")
        receipts.append(receipt)
        assert receipts[1]["key"] == receipts[2]["key"], "resume duplicated the child's tile"
        receipt, _ = run_case(args.pi, directory, agent, state_dir, "failure", failure=True)
        receipts.append(receipt)
        assert len(json.loads((state_dir/"state.json").read_text())["rows"]) == 3
        (directory/"verification.json").write_text(json.dumps(receipts, indent=2)+"\n")
        print("PASS: native Pi parent, child, resume, failure, and shutdown dispatch (offline provider)")
        if args.output:
            print(f"Receipts: {directory/'verification.json'}")
    finally:
        if not args.output:
            shutil.rmtree(directory)


if __name__ == "__main__":
    main()
