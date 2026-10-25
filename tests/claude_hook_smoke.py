#!/usr/bin/env python3
"""Optional macOS smoke test of native Claude hook dispatch, with no external model.

Run with Python 3.15 and --claude-bin /absolute/path/to/the/native/claude.
Use the native executable: vendor launchers can configure IDE integrations.
"""

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mxbridge.install import definition

PROMPT = "Offline hook integration check."
RESPONSE = "Offline fixture complete."


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data":[],"has_more":false}')

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 2 * 1024 * 1024:
            self.send_error(413)
            return
        data = json.loads(self.rfile.read(size))
        self.server.received.append(self.path)
        if "count_tokens" in self.path:
            body = json.dumps({"input_tokens": 10}).encode()
            content_type = "application/json"
        else:
            message = dict(id="msg_fixture", type="message", role="assistant",
                           model=data.get("model", "fixture"), content=[], stop_reason=None,
                           stop_sequence=None, usage=dict(input_tokens=10, output_tokens=0))
            if data.get("stream"):
                events = [
                    ("message_start", dict(type="message_start", message=message)),
                    ("content_block_start", dict(type="content_block_start", index=0,
                                                content_block=dict(type="text", text=""))),
                    ("content_block_delta", dict(type="content_block_delta", index=0,
                                                delta=dict(type="text_delta", text=RESPONSE))),
                    ("content_block_stop", dict(type="content_block_stop", index=0)),
                    ("message_delta", dict(type="message_delta",
                                           delta=dict(stop_reason="end_turn", stop_sequence=None),
                                           usage=dict(output_tokens=5))),
                    ("message_stop", dict(type="message_stop")),
                ]
                body = "".join("event: " + kind + "\ndata: " + json.dumps(value) + "\n\n"
                               for kind, value in events).encode()
                content_type = "text/event-stream"
            else:
                message.update(content=[dict(type="text", text=RESPONSE)],
                               stop_reason="end_turn", usage=dict(input_tokens=10, output_tokens=5))
                body = json.dumps(message).encode()
                content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude-bin", type=Path, required=True,
                        help="Native Claude executable, not an IDE-configuring vendor launcher")
    args = parser.parse_args()
    sandbox = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or not sandbox.is_file():
        parser.error("This smoke test requires macOS sandbox-exec to restrict network access")
    native = args.claude_bin.expanduser().resolve()
    if not native.is_file() or not os.access(native, os.X_OK):
        parser.error("--claude-bin must name an executable file")
    with native.open("rb") as binary:
        if binary.read(2) == b"#!":
            parser.error("--claude-bin must name the native binary, not a launcher script")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    server.received = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="mx-claude-dispatch-") as folder:
            base = Path(folder)
            config = base / "config"
            config.mkdir()
            state = base / "state"
            settings = definition(ROOT / "bridge.py", client="claude")
            observer = base / "observe.py"
            observer.write_text(
                'import json,sys,pathlib\np=json.load(sys.stdin)\n'
                'with pathlib.Path(sys.argv[1]).open("a") as f:\n'
                '    f.write(str(p.get("hook_event_name"))+"\\n")\n')
            for groups in settings["hooks"].values():
                groups[0]["hooks"].append(dict(
                    type="command",
                    command=shlex.join([sys.executable, str(observer), str(base / "events.txt")]),
                    timeout=2, onFailure="continue"))
            (config / "settings.json").write_text(json.dumps(settings))
            env = dict(os.environ)
            for key in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                        "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_AUTH_TOKEN",
                        "MX_CODEX_RUN_ID", "MX_CODEX_LABEL", "MX_BRIDGE_CLIENT", "MX_BRIDGE_INSTANCE"):
                env.pop(key, None)
            env.update(
                CLAUDE_CONFIG_DIR=str(config), ANTHROPIC_API_KEY="offline-fixture-key",
                ANTHROPIC_BASE_URL=f"http://127.0.0.1:{server.server_port}",
                MX_CODEX_STATE_DIR=str(state), CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
                DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", DISABLE_AUTOUPDATER="1")
            policy = ('(version 1)(allow default)(deny network-outbound)'
                      f'(allow network-outbound (remote ip "localhost:{server.server_port}"))')
            command = [
                str(sandbox), "-p", policy, str(native),
                "--setting-sources", "user", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--disable-slash-commands", "--tools", "", "--no-session-persistence",
                "--system-prompt", "Reply with the fixture response.", "--model", "claude-sonnet-4-5",
                "-p", PROMPT,
            ]
            child = subprocess.Popen(
                command, env=env, cwd=base, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, start_new_session=True)
            try:
                stdout, stderr = child.communicate(timeout=25)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                stdout, stderr = child.communicate()
                print("Probe timed out")
            print("Native Claude exit:", child.returncode,
                  "loopback requests:", len(server.received))
            events_path = base / "events.txt"
            events = events_path.read_text().splitlines() if events_path.exists() else []
            print("Hook events:", events)
            if child.returncode != 0:
                print("stdout tail:", stdout[-800:])
                print("stderr tail:", stderr[-1600:])
            assert child.returncode == 0 and server.received, "Native CLI did not complete through the fixture"
            assert RESPONSE in stdout, "Native CLI did not return the fixture response"
            assert {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"} <= set(events), events
            state_path = state / "state.json"
            assert state_path.is_file(), "Native hooks did not write bridge state"
            raw_state = state_path.read_text()
            data = json.loads(raw_state)
            assert len(data["rows"]) == 1 and data["rows"][0]["client"] == "claude", data["rows"]
            assert data["rows"][0]["status"] == "CLOSED", data["rows"][0]["status"]
            assert PROMPT not in raw_state and RESPONSE not in raw_state, "Bridge retained conversation content"
            print("PASS: native Claude dispatched lifecycle hooks to the bridge through a loopback fixture")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
