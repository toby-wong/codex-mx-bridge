import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

from mxbridge.adapters import normalize
from mxbridge.ssh import decode
from mxbridge.state import Store, apply_event, empty, export_snapshot, run_start, run_update

ROOT = Path(__file__).resolve().parent.parent


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.state = empty()

    def event(self, client, name, sid="shared", **extra):
        return apply_event(self.state, dict(session_id=sid, hook_event_name=name,
                           cwd="/private/project", **extra), {}, 100, client=client)

    def test_clients_and_instances_have_independent_identity(self):
        for client, event in (("codex", "SessionStart"), ("claude", "SessionStart"),
                              ("kiro", "agentSpawn")):
            self.event(client, event)
        apply_event(self.state, dict(session_id="shared", hook_event_name="SessionStart"),
                    {}, 100, client="claude", instance="second")
        rows = self.state["rows"]
        self.assertEqual(len({r["key"] for r in rows}), 4)
        self.assertEqual(rows[0]["key"], "shared")
        self.assertEqual([r["client"] for r in rows], ["codex", "claude", "kiro", "claude"])
        self.event("kiro", "stop")
        self.assertEqual([r["status"] for r in rows], ["READY", "READY", "TURN STOP", "READY"])

    def test_claude_lifecycle_and_tool_failure_is_not_session_failure(self):
        for event, status in (("SessionStart", "READY"), ("UserPromptSubmit", "WORKING"),
                              ("PreToolUse", "TOOL"), ("PermissionRequest", "APPROVAL?"),
                              ("PostToolUseFailure", "WORKING"), ("PreCompact", "COMPACT"),
                              ("PostCompact", "WORKING"), ("StopFailure", "TURN ERROR"),
                              ("UserPromptSubmit", "WORKING"), ("Stop", "TURN STOP"),
                              ("SessionEnd", "CLOSED")):
            with self.subTest(event=event):
                self.assertTrue(self.event("claude", event))
                self.assertEqual(self.state["rows"][0]["status"], status)

    def test_claude_child_tool_events_do_not_change_parent_or_sibling(self):
        self.event("claude", "UserPromptSubmit", prompt_id="p")
        self.event("claude", "SubagentStart", agent_id="a", agent_type="reviewer")
        self.event("claude", "SubagentStart", agent_id="b", agent_type="worker")
        self.event("claude", "PreToolUse", agent_id="a", prompt_id="p")
        self.assertEqual([r["status"] for r in self.state["rows"]], ["WORKING", "TOOL", "WORKING"])
        self.event("claude", "PostToolUse", agent_id="a", prompt_id="p")
        self.event("claude", "SubagentStop", agent_id="a", prompt_id="p")
        self.assertEqual([r["status"] for r in self.state["rows"]], ["WORKING", "STOPPED", "WORKING"])
        self.assertEqual(self.state["rows"][1]["name"], "reviewer")
        with self.assertRaises(ValueError):
            self.event("claude", "SubagentStop")

    def test_claude_prompt_identity_rejects_old_terminal_and_tool_events(self):
        self.event("claude", "UserPromptSubmit", prompt_id="new")
        for event in ("PostToolUse", "PermissionRequest", "Stop", "StopFailure", "PostCompact"):
            self.assertFalse(self.event("claude", event, prompt_id="old"))
        self.assertEqual(self.state["rows"][0]["status"], "WORKING")
        self.event("claude", "SessionStart", source="compact")
        self.assertEqual(self.state["rows"][0]["turn_id"], "new")
        self.assertFalse(self.event("claude", "PostToolUse", prompt_id="old"))
        self.event("claude", "UserPromptSubmit")
        self.assertEqual(self.state["rows"][0]["turn_id"], "")

    def test_stop_continuation_requires_fresh_activity_not_just_a_late_result(self):
        for client, start, pre, post, stop in (
            ("claude", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"),
            ("kiro", "userPromptSubmit", "preToolUse", "postToolUse", "stop"),
        ):
            self.event(client, start)
            self.event(client, stop)
            self.assertFalse(self.event(client, post))
            self.assertTrue(self.event(client, pre))
            self.assertTrue(self.event(client, post))
            self.event(client, "SessionEnd")
            self.assertFalse(self.event(client, pre))
        self.assertTrue(all(r["status"] == "CLOSED" for r in self.state["rows"]))

    def test_claude_subagent_can_continue_after_stop_but_not_after_process_exit(self):
        env = dict(MX_CODEX_RUN_ID="run", MX_BRIDGE_CLIENT="claude")
        for event in ("SubagentStart", "SubagentStop"):
            apply_event(self.state, dict(session_id="parent", agent_id="child",
                        hook_event_name=event), env, 100, client="claude")
        self.assertFalse(self.event("claude", "PostToolUse", sid="parent", agent_id="child"))
        self.assertTrue(self.event("claude", "PreToolUse", sid="parent", agent_id="child"))
        self.assertEqual(self.state["rows"][0]["status"], "TOOL")
        run_update(self.state, "run", 101, 1)
        self.assertFalse(self.event("claude", "PreToolUse", sid="parent", agent_id="child"))
        self.assertEqual(self.state["rows"][0]["status"], "EXIT ERROR")

    def test_kiro_legacy_and_current_spellings_address_the_same_session(self):
        for event, status in (("agentSpawn", "READY"), ("UserPromptSubmit", "WORKING"),
                              ("preToolUse", "TOOL"), ("PostToolUse", "WORKING"),
                              ("stop", "TURN STOP"), ("AgentSpawn", "READY"),
                              ("SessionEnd", "CLOSED")):
            self.event("kiro", event)
            self.assertEqual(self.state["rows"][0]["status"], status)
        self.assertEqual(len(self.state["rows"]), 1)
        for unknown in ("PermissionRequest", "SubagentStop", "PreCompact", "Notification"):
            self.assertFalse(self.event("kiro", unknown))

    def test_new_clients_reject_missing_or_truncated_identities(self):
        for client, event in (("claude", "SessionStart"), ("kiro", "agentSpawn")):
            for sid in ("", " ", None, 42, "x" * 513, "bad\nid"):
                with self.subTest(client=client, sid_type=type(sid).__name__), self.assertRaises(ValueError):
                    self.event(client, event, sid=sid)
        self.assertEqual(self.state["rows"], [])
        self.event("claude", "SessionStart", sid="x" * 511 + "a")
        self.event("claude", "SessionStart", sid="x" * 511 + "b")
        self.assertNotEqual(self.state["rows"][0]["key"], self.state["rows"][1]["key"])

    def test_identity_tuple_cannot_collide_through_delimiters(self):
        parent = normalize("claude", dict(session_id="s/agent/a", hook_event_name="PreToolUse"))
        child = normalize("claude", dict(session_id="s", agent_id="a", hook_event_name="PreToolUse"))
        self.assertNotEqual(parent.key, child.key)

    def test_only_safe_metadata_reaches_state_and_remote_export(self):
        for client, event in (("claude", "UserPromptSubmit"), ("kiro", "userPromptSubmit")):
            self.event(client, event, prompt="SECRET", tool_input={"command": "SECRET"},
                       tool_response="SECRET", transcript_path="/SECRET/transcript",
                       last_assistant_message="SECRET", assistant_text="SECRET")
        self.assertNotIn("SECRET", json.dumps(self.state))
        self.assertNotIn("/private", json.dumps(self.state))
        self.assertEqual(self.state["hook_health"]["kiro"]["last_event"], "userPromptSubmit")
        self.event("claude", "StopFailure")
        rows = decode(json.dumps(export_snapshot(self.state, 101)), now=200)
        self.assertEqual([r["client"] for r in rows], ["claude", "kiro"])
        self.assertEqual(rows[0]["status"], "TURN ERROR")
        self.assertTrue(all(not r["iterm_id"] and not r["herdr_socket"] for r in rows))
        self.assertEqual(export_snapshot(self.state, 1100)["rows"][0]["status"], "STALE")

    def test_legacy_rows_and_remote_snapshots_default_to_codex(self):
        self.event("codex", "SessionStart")
        row = self.state["rows"][0]
        del row["client"]
        del row["source_instance"]
        self.event("codex", "UserPromptSubmit")
        self.assertEqual(len(self.state["rows"]), 1)
        self.assertEqual(decode(json.dumps(export_snapshot(self.state, 101)), 200)[0]["client"], "codex")

    def test_another_client_does_not_inherit_launcher_liveness(self):
        env = dict(MX_CODEX_RUN_ID="r", MX_BRIDGE_CLIENT="claude")
        run_start(self.state, "r", "wrapped", env, 100, client="claude")
        apply_event(self.state, dict(session_id="nested", hook_event_name="agentSpawn"),
                    env, 101, client="kiro")
        self.assertEqual(self.state["rows"][1]["run_id"], "")
        apply_event(self.state, dict(session_id="parent", hook_event_name="SessionStart"),
                    env, 102, client="claude")
        self.assertEqual(len(self.state["rows"]), 2)
        run_update(self.state, "r", 103, 0)
        self.assertEqual([r["status"] for r in self.state["rows"]], ["READY", "CLOSED"])

    def test_resume_refreshes_focus_and_detaches_old_wrapper(self):
        for client, name in (("claude", "SessionStart"), ("kiro", "agentSpawn")):
            payload = dict(session_id=client, hook_event_name=name)
            apply_event(self.state, payload, dict(ITERM_SESSION_ID="old", MX_CODEX_RUN_ID="r",
                        MX_BRIDGE_CLIENT=client), 100, client=client)
            apply_event(self.state, payload, dict(HERDR_ENV="1", ITERM_SESSION_ID="obsolete",
                        HERDR_SOCKET_PATH="/tmp/herdr.sock"), 101, client=client)
        self.assertTrue(all(r["run_id"] == "" and r["iterm_id"] == "" for r in self.state["rows"]))


class HookProcessTests(unittest.TestCase):
    def invoke(self, directory, client, payload, *extra):
        return subprocess.run([sys.executable, str(ROOT/"bridge.py"), "--state-dir", str(directory),
                               "hook", "--client", client, *extra], input=payload,
                              capture_output=True, text=True, timeout=5)

    def test_command_hooks_are_silent_on_success_and_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            for client, event in (("claude", "SessionStart"), ("kiro", "agentSpawn")):
                for payload in ('SECRET-invalid', '[]', '{}', json.dumps(
                    dict(session_id="native", hook_event_name=event))):
                    result = self.invoke(folder, client, payload)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertEqual(len(Store(folder).read()["rows"]), 2)
            self.assertNotIn("SECRET", "".join(p.read_text() for p in Path(folder).glob("*.txt")))

    def test_failed_state_creation_and_argument_errors_are_also_advisory(self):
        with tempfile.TemporaryDirectory() as folder:
            bad = Path(folder)/"file"
            bad.write_text("keep")
            for client in ("claude", "kiro"):
                for path, extra in ((bad, ()), (Path(folder)/"state", ("--unknown", "SECRET"))):
                    result = self.invoke(path, client, "{}", *extra)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertEqual(bad.read_text(), "keep")

    @unittest.skipUnless(hasattr(signal, "setitimer"), "Hook deadline targets macOS/Linux")
    def test_reader_deadline_precedes_host_timeout_when_stdin_stays_open(self):
        with tempfile.TemporaryDirectory() as folder:
            child = subprocess.Popen([sys.executable, str(ROOT/"bridge.py"), "--state-dir", folder,
                                      "hook", "--client", "kiro"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertEqual(child.wait(timeout=3), 0)
                self.assertEqual(child.stdout.read(), b"")
                self.assertEqual(child.stderr.read(), b"")
                self.assertTrue((Path(folder)/"hook-kiro-error.txt").exists())
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate()

    def test_import_failure_does_not_turn_into_an_agent_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            entry = Path(folder)/"bridge.py"
            shutil.copy2(ROOT/"bridge.py", entry)
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            for client in ("codex", "claude", "kiro"):
                result = subprocess.run([sys.executable, str(entry), "hook", "--client", client],
                    cwd=folder, env=env, input="{}", capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), "{}" if client == "codex" else "")
                self.assertEqual(result.stderr, "")

    def test_old_interpreter_remains_advisory_without_importing_the_package(self):
        for client in ("codex", "claude", "kiro"):
            code = ("import runpy,sys; sys.version_info=(3,14,0); "
                    "sys.argv=['bridge.py','hook','--client',sys.argv[1]]; "
                    f"runpy.run_path({str(ROOT/'bridge.py')!r},run_name='__main__')")
            result = subprocess.run([sys.executable, "-c", code, client], capture_output=True,
                                    text=True, timeout=5)
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            self.assertEqual(result.stdout.strip(), "{}" if client == "codex" else "")

    def test_concurrent_client_hooks_do_not_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as folder:
            def invoke(i):
                client = ("codex", "claude", "kiro")[i % 3]
                event = "agentSpawn" if client == "kiro" else "SessionStart"
                return self.invoke(folder, client, json.dumps(dict(
                    session_id=str(i // 3), hook_event_name=event)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(invoke, range(18)))
            self.assertTrue(all(r.returncode == 0 for r in results))
            self.assertEqual(len(Store(folder).read()["rows"]), 18)


if __name__ == "__main__":
    unittest.main()
