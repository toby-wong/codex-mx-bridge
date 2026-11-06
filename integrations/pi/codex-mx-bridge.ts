// Observational Pi integration. Installed with an absolute bridge command.
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, join } from "node:path";

const DEFAULT_OPTIONS = { command: [] }; // Replaced by the bridge installer.

/** At most one writer and 32 queued observations; status snapshots coalesce. */
export function createTransport(options) {
  const queue = [];
  let running = false, stopped = false, active, lastError = 0;
  async function failure() {
    if (Date.now() - lastError < 60000) return;
    lastError = Date.now();
    const directory = process.env.MX_CODEX_STATE_DIR ||
      join(homedir(), ".local", "state", "codex-mx-bridge");
    try {
      await mkdir(directory, { recursive: true, mode: 0o700 });
      await writeFile(join(directory, "hook-pi-error.txt"),
        "Pi bridge reporting failed; check the installed Python command and state directory.\n",
        { mode: 0o600 });
    } catch {}
  }
  function send(payload) {
    return new Promise((resolve) => {
      let finished = false, timer;
      const finish = (ok) => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        active = undefined;
        if (!ok) void (options.onError || failure)();
        resolve();
      };
      try {
        const child = spawn(options.command[0], options.command.slice(1),
          { stdio: ["pipe", "ignore", "ignore"], windowsHide: true });
        active = child;
        child.once("error", () => finish(false));
        child.once("close", (code) => finish(code === 0));
        child.stdin.on("error", () => {});
        timer = setTimeout(() => { child.kill("SIGKILL"); finish(false); },
          options.timeoutMs ?? 1300);
        timer.unref?.();
        child.stdin.end(JSON.stringify(payload) + "\n");
      } catch { finish(false); }
    });
  }
  async function drain() {
    if (running || stopped) return;
    running = true;
    try {
      while (queue.length && !stopped) await send(queue.shift().payload);
    } finally { running = false; }
  }
  return {
    enqueue(payload) {
      if (stopped) return;
      const key = payload.child?.session_path || "status";
      // Remove and append: replacing in place would put a newer sequence
      // ahead of older child-association observations.
      const index = queue.findIndex(item => item.key === key);
      if (index >= 0) queue.splice(index, 1);
      if (queue.length >= 32) queue.shift();
      queue.push({ key, payload });
      void drain();
    },
    async close() {
      const deadline = Date.now() + 1800;
      while ((running || queue.length) && Date.now() < deadline)
        await new Promise(resolve => setTimeout(resolve, 10));
      stopped = true;
      queue.length = 0;
      active?.kill("SIGKILL");
    },
  };
}

/** Exported for lifecycle tests; Pi calls the default factory below. */
export function observePi(pi, options) {
  const transport = options.transport || createTransport(options);
  const env = options.env || process.env;
  const now = options.now || (() => Date.now() / 1000);
  const attachment = randomUUID(), startedAt = now();
  let sequence = 0, snapshot, heartbeat, closed = false;
  let active = false, waiting = false, compacting = false;
  let settled = "READY", outcome = "completed", activityAt = startedAt;
  const tools = new Set();

  function status() {
    if (waiting) return "WAITING";
    if (compacting) return "COMPACT";
    if (tools.size) return "TOOL";
    return active ? "WORKING" : settled;
  }
  function capture(ctx) {
    const manager = ctx.sessionManager;
    const id = manager.getSessionId();
    const path = manager.getSessionFile() || "";
    const child = !!env.PI_SUBAGENT_ID &&
      (!env.PI_SUBAGENT_SESSION || env.PI_SUBAGENT_SESSION === path);
    const header = manager.getHeader?.();
    const created = Date.parse(header?.timestamp || "") / 1000;
    const fallbackName = (child ? env.PI_SUBAGENT_NAME : "") || basename(ctx.cwd || "") || "Pi";
    snapshot = {
      schema_version: 1, session_id: id, session_path: path,
      name: manager.getSessionName?.() || fallbackName, fallback_name: fallbackName,
      kind: child ? "subagent" : "session",
      launch_id: child ? env.PI_SUBAGENT_ID : "",
      agent_role: child ? env.PI_SUBAGENT_AGENT || "" : "",
      parent_session_path: child ? header?.parentSession || "" : "",
      mode: ctx.mode === "tui" ? "tui" : "headless",
      created_at: Number.isFinite(created) && created >= 0 ? created : startedAt,
    };
  }
  function report(name, ctx, { activity = true, reason = "", child } = {}) {
    if (closed) return;
    try {
      if (ctx) capture(ctx);
      if (!snapshot) return;
      if (activity) activityAt = now();
      transport.enqueue({
        ...snapshot, hook_event_name: name, reason, status: status(),
        attachment_id: attachment, attachment_started_at: startedAt,
        sequence: ++sequence, activity_at: activityAt,
        ...(child ? { child } : {}),
      });
    } catch {} // Disposed contexts and display errors never affect Pi.
  }
  function on(name, handler) {
    pi.on(name, (event, ctx) => {
      if (closed) return;
      try { return handler(event, ctx); } catch {}
    });
  }
  on("session_start", (event, ctx) => {
    active = ctx.isIdle() === false;
    // Zero means retain activity already observed before this extension reload.
    if (event.reason === "reload") activityAt = 0;
    report("session_start", ctx, { activity: event.reason !== "reload", reason: event.reason });
    clearInterval(heartbeat);
    heartbeat = setInterval(() => report("heartbeat", null, { activity: false }),
      options.heartbeatMs ?? 15000);
    heartbeat.unref?.();
  });
  on("session_info_changed", (_event, ctx) =>
    report("session_info_changed", ctx, { activity: false }));
  on("agent_start", (_event, ctx) => {
    active = true;
    settled = "READY";
    outcome = "completed";
    report("agent_start", ctx);
  });
  on("agent_before_settle", (event) => { outcome = event.outcome; });
  on("agent_settled", (event, ctx) => {
    if (ctx.isIdle() === false) return;
    active = false;
    tools.clear();
    compacting = false;
    settled = event.aborted ? "INTERRUPTED" : outcome === "error" ? "TURN ERROR" : "TURN STOP";
    report("agent_settled", ctx);
  });
  on("tool_execution_start", (event, ctx) => {
    tools.add(event.toolCallId);
    report("tool_execution_start", ctx);
  });
  on("tool_execution_end", (event, ctx) => {
    tools.delete(event.toolCallId);
    report("tool_execution_end", ctx);
    // Pi Herdr Agents 3.7.x: only identity fields from structured launch results.
    // Never send the tool's arguments, task, summary, content, or error text.
    if (!event.isError && ["subagent", "subagent_resume"].includes(event.toolName)) {
      const details = event.result?.details;
      const path = details?.sessionFile || details?.sessionPath;
      if (typeof path === "string" && typeof details?.id === "string" &&
          ["started", "uncertain"].includes(details.status))
        report("child_started", ctx, { activity: false,
          child: { session_path: path, launch_id: details.id } });
    }
  });
  on("ui_prompt_start", (_event, ctx) => {
    waiting = true;
    report("ui_prompt_start", ctx);
  });
  on("ui_prompt_end", (_event, ctx) => {
    waiting = false;
    report("ui_prompt_end", ctx);
  });
  on("session_before_compact", (_event, ctx) => {
    compacting = true;
    report("session_before_compact", ctx);
  });
  for (const name of ["session_compact", "session_compact_failed"])
    on(name, (_event, ctx) => {
      compacting = false;
      report(name, ctx);
    });
  on("session_shutdown", async (event, ctx) => {
    clearInterval(heartbeat);
    if (event.reason !== "reload") {
      active = waiting = compacting = false;
      tools.clear();
      settled = "CLOSED";
    }
    report("session_shutdown", ctx, { activity: event.reason !== "reload", reason: event.reason });
    closed = true;
    await transport.close();
  });
  return transport;
}

export default function (pi) {
  if (DEFAULT_OPTIONS.command.length) observePi(pi, DEFAULT_OPTIONS);
}
