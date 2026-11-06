import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

// The extension deliberately uses only JavaScript syntax and Node builtins.
const source = await readFile(new URL("../integrations/pi/codex-mx-bridge.ts", import.meta.url), "utf8");
const { observePi, createTransport } = await import("data:text/javascript;base64," +
  Buffer.from(source).toString("base64"));

function harness(options = {}) {
  const events = new Map(), packets = [];
  let time = 100;
  const context = {
    cwd: "/work/project", mode: "tui", idle: true, isIdle() { return this.idle; },
    sessionManager: {
      getSessionId: () => "native-id", getSessionFile: () => "/sessions/pi.jsonl",
      getHeader: () => ({ timestamp: "1970-01-01T00:01:20Z" }), getSessionName: () => "My chat",
    },
  };
  observePi({ on: (name, handler) => events.set(name, handler) }, {
    transport: { enqueue: payload => packets.push(payload), close: async () => {} },
    heartbeatMs: 1000000, env: {}, now: () => time, ...options,
  });
  return { context, events, packets, advance: () => ++time,
    emit: (name, event = {}) => events.get(name)?.({ type: name, ...event }, context),
    last: () => packets.at(-1) };
}

test("parallel tools, UI waiting and final settlement use native boundaries", async t => {
  const h = harness();
  t.after(() => h.emit("session_shutdown", { reason: "quit" }));
  await h.emit("session_start", { reason: "startup" });
  assert.equal(h.last().status, "READY");
  h.context.idle = false;
  await h.emit("agent_start");
  await h.emit("tool_execution_start", { toolCallId: "a", args: "SECRET" });
  await h.emit("tool_execution_start", { toolCallId: "b" });
  await h.emit("tool_execution_end", { toolCallId: "a", isError: true, result: "SECRET" });
  assert.equal(h.last().status, "TOOL");
  await h.emit("ui_prompt_start", { title: "SECRET" });
  assert.equal(h.last().status, "WAITING");
  await h.emit("ui_prompt_end");
  assert.equal(h.last().status, "TOOL");
  await h.emit("tool_execution_end", { toolCallId: "b" });
  assert.equal(h.last().status, "WORKING");
  assert.equal(h.events.has("agent_end"), false, "low-level end cannot claim final idle");
  await h.emit("agent_before_settle", { outcome: "error" });
  h.context.idle = true;
  await h.emit("agent_settled", { aborted: false });
  assert.equal(h.last().status, "TURN ERROR");
  assert.equal(JSON.stringify(h.packets).includes("SECRET"), false);
});

test("retry, compaction, interruption and rename retain accurate state", async t => {
  const h = harness();
  t.after(() => h.emit("session_shutdown", { reason: "quit" }));
  await h.emit("session_start", { reason: "startup" });
  h.context.idle = false;
  await h.emit("agent_start");
  await h.emit("session_before_compact");
  assert.equal(h.last().status, "COMPACT");
  await h.emit("session_compact_failed", { errorMessage: "SECRET" });
  assert.equal(h.last().status, "WORKING");
  await h.emit("agent_before_settle", { outcome: "error" });
  await h.emit("agent_start"); // Automatic retry begins.
  h.context.idle = true;
  h.advance();
  await h.emit("agent_settled", { aborted: false });
  assert.equal(h.last().status, "TURN STOP");
  const activity = h.last().activity_at;
  h.advance();
  h.context.sessionManager.getSessionName = () => "Renamed";
  await h.emit("session_info_changed");
  assert.equal(h.last().name, "Renamed");
  assert.equal(h.last().activity_at, activity);
  await h.emit("agent_settled", { aborted: true });
  assert.equal(h.last().status, "INTERRUPTED");
});

test("child uses its own native identity and only exports selected launch metadata", async t => {
  const h = harness({ env: { PI_SUBAGENT_ID: "launch-id", PI_SUBAGENT_NAME: "Worker",
    PI_SUBAGENT_SESSION: "/sessions/pi.jsonl", PI_SUBAGENT_AGENT: "frontier" } });
  t.after(() => h.emit("session_shutdown", { reason: "quit" }));
  h.context.sessionManager.getSessionName = () => undefined;
  await h.emit("session_start", { reason: "startup" });
  assert.equal(h.last().session_id, "native-id");
  assert.equal(h.last().launch_id, "launch-id");
  assert.equal(h.last().name, "Worker");
  assert.equal(h.last().agent_role, "frontier");
  assert.equal(h.last().kind, "subagent");
  assert.equal(h.last().parent_session_path, "");
  await h.emit("tool_execution_end", { toolCallId: "spawn", toolName: "subagent", result: {
    content: "SECRET", details: { id: "grandchild", sessionFile: "/sessions/grandchild.jsonl",
      status: "started", task: "SECRET", summary: "SECRET" } } });
  assert.deepEqual(h.last().child, { session_path: "/sessions/grandchild.jsonl", launch_id: "grandchild" });
  assert.equal(JSON.stringify(h.packets).includes("SECRET"), false);
});

test("headless sessions cannot claim TUI focus and shutdown stops old callbacks", async () => {
  const h = harness();
  h.context.mode = "rpc";
  await h.emit("session_start", { reason: "reload" });
  assert.equal(h.last().mode, "headless");
  assert.equal(h.last().activity_at, 0);
  await h.emit("session_shutdown", { reason: "reload" });
  assert.notEqual(h.last().status, "CLOSED");
  const count = h.packets.length;
  await h.emit("agent_start");
  assert.equal(h.packets.length, count);
});

test("writer coalesces snapshots without reversing child association sequence", async t => {
  const directory = await mkdtemp(join(tmpdir(), "mx pi writer ' "));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const file = join(directory, "received.jsonl");
  const writer = createTransport({ command: [process.execPath, "-e",
    `let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>setTimeout(()=>require('fs').appendFileSync(process.argv[1],s),40));`,
    file] });
  writer.enqueue({ sequence: 1 });
  for (let sequence = 2; sequence < 11; sequence++) writer.enqueue({ sequence });
  writer.enqueue({ sequence: 11, child: { session_path: "/sessions/child.jsonl" } });
  writer.enqueue({ sequence: 12 });
  await writer.close();
  const packets = (await readFile(file, "utf8")).trim().split("\n").map(JSON.parse);
  assert.deepEqual(packets.map(p => p.sequence), [1, 11, 12]);
});

test("missing or stuck writers finish quietly within a bounded time", async () => {
  for (const command of [["/nonexistent/mx-python"], [process.execPath, "-e", "setInterval(()=>{},1000)"]]) {
    let failures = 0;
    const start = Date.now();
    const writer = createTransport({ command, timeoutMs: 100, onError: () => { failures++; } });
    writer.enqueue({ sequence: 1 });
    await writer.close();
    assert.equal(failures, 1);
    assert.ok(Date.now() - start < 1500);
  }
});
