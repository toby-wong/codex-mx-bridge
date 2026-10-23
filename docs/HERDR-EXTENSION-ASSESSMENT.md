# Herdr export extension assessment

Assessment date: 24 October 2026 (Australia/Sydney). This is a separate research workstream; no Herdr adapter or extension is implemented by this document.

## Recommendation

Keep the bridge's independent Codex lifecycle hooks as its primary event source. Herdr use does not inherently prevent those hooks from running, locally or on Linux over SSH. Add an **optional external Herdr status adapter** if the bridge needs Herdr's detected agents, pane identity, workspace labels, or status when hook events are unavailable. A Herdr plugin is useful later as a small installation and event-export package; it is not required to obtain status and should not become the bridge's daemon supervisor.

Do not describe this as exporting “Herdr's Codex lifecycle hooks.” Herdr's current Codex integration reports session identity on `SessionStart`; its Codex status comes from terminal-screen detection. Exported Herdr status would therefore be an additional observation source, with different semantics and possible disagreement with the direct Codex hook state. [Herdr integrations](https://herdr.dev/docs/integrations/#codex)

## Evidence and compatibility baseline

Reviewed the official documentation and upstream source at [`6b526626f66e22c08962a7f39a83fc9ac2ebda62`](https://github.com/herdrdev/herdr/tree/6b526626f66e22c08962a7f39a83fc9ac2ebda62), committed 23 October 2026. The manifest identifies that checkout as `0.9.5`; a version string alone does not identify its exact feature set. Also compared release tag `v0.9.5`, commit [`2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`](https://github.com/herdrdev/herdr/tree/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01).

The reviewed event/session schemas, Codex hook script, plugin runtime, and public focus implementation are unchanged between those two commits. Agent parameter declarations were refactored on main; the `AgentInfo` record fields below are unchanged. No installed Herdr binary, user configuration, running Linux server, Mac client, or physical console was available for this assessment. These are source-verified capabilities, not an end-to-end hardware validation.

Before an adapter is enabled, record `herdr --version`, `herdr integration status`, `herdr api schema --json`, and the chosen server's snapshot `version`/`protocol`. Use schema/capability checks and fixtures from that installation. Do not infer a minimum compatible release from the example plugin's `min_herdr_version = "0.7.0"`. [Schema discovery](https://herdr.dev/docs/socket-api/#schema), [manifest version rule](https://herdr.dev/docs/plugins/#manifest)

## What the existing Codex integration actually does

The bundled shell script is marked integration version `10`. It accepts the `session` action, requires `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, and `HERDR_PANE_ID`, and sends `pane.report_agent_session`. Its parameters are `pane_id`, `source: "herdr:codex"`, `agent: "codex"`, `seq`, `agent_session_id`, and optional `session_start_source`. It rejects a different explicit hook event, requires a nonempty transcript path, and rejects a session ID conflicting with inherited `CODEX_THREAD_ID`. It does not forward a lifecycle event feed or report working/blocked/completed states. [Bundled Codex script](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/integration/assets/codex/herdr-agent-state.sh)

Herdr's installer removes its previous lifecycle entries and installs only its own `SessionStart` handler. Keep bridge-owned handlers alongside it, preserving other entries; never edit the Herdr-managed script because reinstalling overwrites it. [Installer source](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/integration/targets.rs#L160)

Official OpenAI documentation supports multiple matching hooks and independently trusted hook sources. The current documented events include `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop`, `Interrupt`, and `SessionEnd`. Changed non-managed hook definitions must be reviewed through `/hooks`. These are Codex APIs, not Herdr APIs. Hooks execute where Codex runs, so Linux sessions need the collector installed on Linux. `transcript_path` is not a stable transcript-parsing interface. `session_id` in subagent hooks identifies the parent session; never assume it distinguishes every subagent. [Official Codex hooks](https://learn.chatgpt.com/docs/hooks)

## Verified export surfaces

| Surface | Verified contract | Consequence for this bridge |
| --- | --- | --- |
| `agent.list` | Request `params: {}`; success `result.type: "agent_list"`, `result.agents` | Simple read-only polling, one server at a time. |
| `agent.get` | `params: {"target":"<live agent name or pane ID>"}`; success `result.agent` | Re-read authoritative current identity/status. |
| `session.snapshot` | `params: {}`; `result.type: "session_snapshot"`, `result.snapshot` includes `version`, `protocol`, `agents`, `workspaces`, `tabs`, `panes`, `layouts`, optional focused IDs | Bootstrap/recover the cache and obtain labels without reading terminal output. CLI: `herdr api snapshot`. |
| `events.subscribe` | Local newline-delimited JSON socket; subscriptions specify dotted `type` names | Optional low-latency invalidation stream, not a durable hook log. |
| Plugin `[[events]]` | `on = "pane.agent_status_changed"` and relevant pane lifecycle names are accepted | Optional short-lived export handlers can request a fresh snapshot and exit. |

The first three shapes are verified in the [response schema](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/response.rs) and [snapshot schema](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/session.rs). The installed schema is the authority for the user's version.

Useful `AgentInfo` fields are `terminal_id`, optional `name`, optional `agent`, `agent_status`, optional `agent_session`, `workspace_id`, `tab_id`, `pane_id`, `focused`, `state_change_seq`, optional `completion_seq`, and `revision`. Optional labels include `title`, `display_agent`, `terminal_title_stripped`, `state_labels`, and `tokens`; paths include optional `cwd`/`foreground_cwd`. `agent_session` has `source`, `agent`, `kind`, and `value`. Status values are exactly `idle`, `working`, `blocked`, `done`, and `unknown`. Fields may be absent according to their serialization rules. [Agent schema](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/agents.rs), [status enum](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/common.rs)

Herdr `done` means idle with an unseen completion; reads do not mark it seen, while explicit focus does. `blocked` means Herdr recognized an approval/question UI. Neither value proves successful task completion. A pane identifies a terminal location; a live agent name is an alias that may be cleared or reused. [Agent automation semantics](https://herdr.dev/docs/agent-automation/#choose-the-control-surface)

### Stream details that must not be invented

For a pane, subscribe using `{"type":"pane.agent_status_changed","pane_id":"w1:p1"}`; optional `agent_status` filters one exact state. The specialized emitted event is `event: "pane.agent_status_changed"` with `data.pane_id`, `workspace_id`, `agent_status`, and optional agent/label fields. General lifecycle envelopes use underscore `event` values such as `pane_created`, with their own tagged `data`. Plugin hook names use dotted names. Parse the declared variants instead of replacing punctuation globally. [Event schema](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/schema/events.rs)

Status subscriptions are pane-scoped, so refresh subscriptions as panes appear, move, or exit. A missing referenced pane rejects the entire subscription request. There is no durable replay or shared sequence boundary with snapshots. On disconnect or `events_lost`, subscribe again, wait for acknowledgment, fetch a snapshot on a second connection, and treat events as invalidations that trigger serialized authoritative reads. Refresh again when an event arrives during a read. [Socket subscription recovery](https://herdr.dev/docs/socket-api/#event-subscriptions)

## Local Mac and remote Linux architecture

Proposed additional component, not part of the delivered implementation:

```text
Codex lifecycle hooks (Mac/Linux) ---------> existing bridge state
Herdr snapshot/status adapter (optional) -> observations + pane/session mapping
Linux private export -- SSH pull --------> Mac bridge -> Logi Actions plugin
```

Start with bounded polling, using `herdr agent list` or `herdr api snapshot`. For saved machines, Herdr already provides `herdr --machine <profile-id> agent list` and `herdr --machine <profile-id> api snapshot` over noninteractive SSH. This does not require an open TUI, does not fall back to Local, and targets one saved remote session. The profile selector must be an enabled profile ID or a unique case-sensitive label; an arbitrary SSH hostname is not a selector. `--machine` cannot be combined with `--session` or `--remote`. There is no documented forwarded raw subscription command in that CLI surface. [Saved-machine CLI contract](https://herdr.dev/docs/cli-reference/#saved-ssh-machines)

For lower latency, run a supervised adapter beside the Linux Herdr server, consume its local socket stream, and write a filtered private export that the existing SSH collector retrieves. Keep the Logitech plugin and device connection on the Mac. Namespace every record by configured host/profile and Herdr session/socket; `w1:p1` and agent names can exist simultaneously on several machines. The local Herdr socket does not represent a single combined multi-machine listing. Herdr does not copy local plugins/configuration/executables to remote hosts. [Machine scope and remote configuration](https://herdr.dev/docs/connecting-machines/#settings-and-automation)

Merge with direct-hook records only when `agent_session.agent == "codex"`, `agent_session.kind == "id"`, and `agent_session.value` matches the Codex session identity within the same host namespace. Otherwise keep a separate Herdr observation. `kind` can also be `path` for other agent integrations; do not equate a path with a Codex session ID. [Session identity types](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/agent_resume.rs#L18)

Preserve `source`, observed time, connection freshness, and the raw status; do not silently overwrite a fresher direct lifecycle event. `terminal_id` helps track a pane move within a server, while a server restart still requires cache replacement. Label Herdr-derived states as detected; disconnects become offline/stale, not done.

## Should a plugin be created?

An external adapter is the recommended first implementation. It can serve both local and remote installations, can be supervised by `launchd`/a Linux service manager, and avoids running an exporter process for every event. This is an architecture recommendation, not an upstream requirement.

A later `herdr-plugin.toml` package can offer an explicit export action plus short `[[startup]]` and `[[events]]` handlers that atomically refresh a status file. Runtime discovery includes `HERDR_SOCKET_PATH`, `HERDR_BIN_PATH`, `HERDR_PLUGIN_CONTEXT_JSON`, and `HERDR_PLUGIN_EVENT_JSON`; files belong in `HERDR_PLUGIN_CONFIG_DIR`/`HERDR_PLUGIN_STATE_DIR`. Herdr does not sandbox plugin code or manage its storage format. Startup hooks are one-shot initialization and do not run merely because a client attaches, a plugin is enabled, or config reloads. They are not supervised daemons. [Plugin lifecycle and environment](https://herdr.dev/docs/plugins/#startup-hooks)

Event handlers can run concurrently; use a single writer/lock, coalesce events, read current state after acquiring the lock, and periodically reconcile even if a plugin handler failed. The reviewed runtime has a 32-command concurrency ceiling and captures command output in logs. Do not print hook payloads or start detached exporters from plugin startup. [Plugin runtime](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/app/api/plugins/runtime.rs)

## Pane focus and unsupported behavior

Herdr supports `agent.focus` with `params: {"target":"w1:p1"}` and `pane.focus` with `params: {"pane_id":"w1:p1"}`. The saved-machine prefix can route these commands to Linux. Current source applies successful public focus **session-wide to attached client-shell views**. It does not expose a public `client_id` selector in those parameters. Manual pane-focus events have different per-client semantics; do not confuse them with an explicit public focus command. [Public focus implementation](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/server/headless/client_views.rs#L809)

Focus also marks completion seen. These APIs do not establish which Mac iTerm2 window contains a particular Herdr client, activate that window, or prove that the intended local client switches from another saved machine. An inherited `ITERM_SESSION_ID` is not enough to identify a pane inside Herdr or an SSH host. Re-read live host/session/agent identity before any future focus action, then use an explicitly configured local window mapping. Keep Herdr and remote button focus disabled until that path is implemented and tested with the user's client topology.

No reviewed API provides a durable replayable stream of all Codex hooks, automatic export of every connected machine through one local socket, or a hook-authenticated guarantee that Herdr screen detection is correct. A Herdr plugin cannot recover Codex lifecycle events that the integration never reported. Independent Codex hooks cover only events the installed CLI actually emits and trusts; crashes and missed events still require stale-state handling.

## Privacy and security requirements

Export an allowlist: configured host alias, opaque session/terminal identifiers, bounded display label, status/source, sequence or revision, and freshness timestamps. Do not export prompts, terminal screens, transcript contents/paths, tool arguments, environment variables, resume commands, arbitrary metadata tokens, or full filesystem paths by default. Titles and labels are also potentially sensitive; sanitize control characters and allow an explicit display-name override.

Use private directories/files (Unix `0700`/`0600`), atomic replacement, input/output size limits, bounded timeouts, and one writer. Retain host-key checking and user-managed SSH authentication. Never expose the raw Herdr socket over TCP: its API can send input and control processes. The upstream Unix API socket is restricted to `0600`, but access is still equivalent to powerful local automation. [Socket permission source](https://github.com/herdrdev/herdr/blob/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/src/api/server.rs#L31)

Use a fixed allowlisted export command or file for SSH collection; never form shell commands from remote labels/pane names. A read-only collector should neither install Herdr nor restart its server. Keep focus/control opt-in and separate from status collection.

## Acceptance criteria for a future adapter/plugin

1. **Compatibility:** fixtures from the user's binary/schema parse successfully; absent optional fields work; unsupported protocol/fields fail visibly without changing Codex or Herdr configuration.
2. **Coexistence:** install/uninstall either integration preserves the other's exact hook definitions. Both handlers run after `/hooks` trust review; Herdr retains the correct Codex session across resume and server restoration.
3. **Identity:** two hosts with `w1:p1`, two named sessions, reused agent names, nested agents, and missing native session identity remain distinct. Cross-workspace pane moves update the public pane ID without duplicating the terminal.
4. **Semantics:** working, approval/question UI, stop, interrupt, exit, idle-after-completion, and unknown states retain their provenance. Herdr's seen completion behavior is tested independently of hook stop events.
5. **Recovery:** restarts, stale exports, auth failure, lost SSH, malformed/oversize JSON, `events_lost`, invalid pane subscriptions, and an event arriving during snapshot refresh cannot produce false completion or a wrong-host control action.
6. **Concurrency/privacy:** simultaneous plugin handlers cannot overwrite newer snapshots; exporter output/logs contain no prompt, transcript, environment, or unapproved paths; partial files are never consumed.
7. **Remote scope:** a saved profile queries only its configured server/session, works without an open TUI, and fails without Local fallback. Collection does not restart the Linux server or install software.
8. **Focus gate:** before enabling any button action, demonstrate the exact Mac iTerm2/Herdr view and remote machine selected with multiple clients attached; explicitly accept the session-wide focus/seen effects. Missing mappings or replaced occupants must result in no action.

These are proposed tests for the optional future workstream. They have not been run as part of this assessment; the existing bridge tests do not validate a Herdr adapter that is not implemented.
