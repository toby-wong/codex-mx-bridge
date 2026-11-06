# Pi and Pi Herdr Agents integration plan

Status: original assessment and implementation plan. The integration is now
implemented; see [Pi setup](PI.md) for the supported behavior and activation steps.
Checked 6 November 2026 against the installed packages, their upstream sources,
and live Herdr metadata on the local Mac and cloud desktop.

Pi sessions and `pi-herdr-agents` children can feed the existing bridge. Add a
Pi extension that reports lifecycle events, a Python adapter, and Pi-specific
Herdr identity matching. Each child should have its own button because it runs
its own Pi process and session.

## Verified starting point

| Component | Local Mac | Cloud desktop |
| --- | --- | --- |
| Pi | `@earendil-works/pi-coding-agent` 1.5.0 | Same |
| Pi Herdr Agents | 3.7.2 | Same |
| Herdr | 0.9.5 | Same |
| Native Herdr Pi extension | Integration version 9 | Identical file |
| Pi panes in the inspected Herdr session | None at inspection | One parent and one delegated child |
| Bridge | Current checkout has Codex, Claude, and Kiro adapters | Installed release predates the adapter layer |

The cloud parent reported `done`; its child reported `working`. The child's
environment supplied a launch ID, name, and `frontier` role. Herdr reported
both occupants as `agent: "pi"` with `agent_session.kind: "path"`.

The inspected child's native Pi session ID differed from its launch ID and the
IDs in its filename. Its session header did not contain `parentSession`.
The package source explains this: standalone children do not receive the
seeded parent header used by forked children. Neither filenames nor a missing
parent header can reliably identify a child or its parent.

These were read-only checks. No existing Pi session was reloaded, prompted,
moved, or stopped. Bridge-to-Pi event delivery and Pi button focus remain to
be implemented and tested.

## 1. Add a Pi extension and adapter

Install a bridge-owned `codex-mx-bridge.ts` in the selected Pi agent directory's
`extensions/` folder. The default is `~/.pi/agent/extensions/`. Preserve the
existing `herdr-agent-state.ts` and `bedrock-performance.ts`.

The extension would send a small JSON observation to:

```text
<installed-python> <installed-bridge.py> hook --client pi
```

Use the installer's absolute interpreter and release paths. Serialize writes,
bound subprocess lifetime and queue size, and discard stdout. Reporting failure
must leave the Pi run and user prompts unaffected. Register observers; return
no permission, prompt, tool, or model overrides.

Capture native session ID and file path through
`ctx.sessionManager.getSessionId()` and `getSessionFile()`. Read chat names
through `getSessionName()` and observe `session_info_changed`. Export only
identity, display metadata, lifecycle state, and timestamps. Do not send prompt
text, tool arguments, output, session contents, or provider credentials.

| Pi observation | Bridge behavior |
| --- | --- |
| `session_start` | Create or reattach the native session; initialize from current idle/busy state |
| `session_info_changed` | Refresh the name without resetting activity or status |
| `agent_start` | `WORKING` |
| `tool_execution_start` / `tool_execution_end` | Track outstanding tool IDs; show `TOOL` until all outstanding tools finish |
| `ui_prompt_start` / `ui_prompt_end` | Show `WAITING`, then restore the current underlying state |
| Compaction start, success, or failure | Show `COMPACT` during compaction, then restore activity according to Pi's lifecycle |
| `agent_settled` | `TURN STOP`, or `INTERRUPTED` when `aborted` is true |
| Final error outcome followed by settlement | `TURN ERROR`; intermediate errors and retries remain active |
| `session_shutdown` | Close the old attachment on quit or session replacement; handle reload without a false completion |

`agent_end` is not Pi's final idle signal: retries, compaction, queued messages,
and extension continuations can follow it. Use `agent_settled`. Record the
documented `agent_before_settle.outcome` without modifying that boundary, and
verify final-error handling with a local fake provider before enabling it.

`WAITING` needs a shared status and pet mapping. Pi's UI events describe generic
extension dialogs, so displaying every dialog as a permission approval would
be inaccurate. Their callbacks are best effort and are not awaited by Pi;
capture observations immediately and serialize their delivery.

An extension heartbeat should extend the session's presence lease without
changing its activity timestamp. This keeps long-running and idle Pi sessions
visible without promoting them into the nine most recent chats. Scope queued
events and heartbeats to their session attachment so a late event cannot
overwrite a replacement session after `/new`, `/resume`, `/fork`, or `/reload`.

## 2. Give each child a native session row

Use `(client="pi", source instance, native Pi session ID)` for row identity.
Keep child classification separate from the key:

| Metadata | Source |
| --- | --- |
| Session ID and current session path | Pi session-manager API |
| Child classification and launch ID | `PI_SUBAGENT_ID` |
| Child display name | `PI_SUBAGENT_NAME` |
| Role, when present | `PI_SUBAGENT_AGENT` |
| Parent relationship, when present | Verified launch metadata or session header |

Unlike the existing Codex/Claude child events, a Pi child owns a separate
session ID. Do not force it into the shared-parent `session_id + child_id`
representation. Resuming a child can allocate a new launch ID while retaining
its native session; that should update one row, not create duplicates.

The installed package launches normal Pi processes and adds its own child
extension with `-e`; it does not disable global extensions on that path.
Ordinary children therefore load the bridge extension from their selected Pi
agent directory. Persistent specialists stay visible between tasks, while
disposable children close their row when their process exits.

For parent association, the parent's `subagent` tool result exposes structured
`details` containing `id`, `name`, optional `agent`, and `sessionFile`.
`subagent_resume` uses `sessionPath`. A version-checked observer can extract
only those fields and join them to the child's own observation. Do not copy
the result's task or summary, create a second child row, or infer a parent from
pane position. Keep the parent unknown when no verified relationship exists.

Custom `PI_CODING_AGENT_DIR` installations need explicit setup. The package can
select a project's `.pi/agent` directory, including in a worktree; a global
installation alone does not guarantee coverage there. Provide a selected
`--pi-agent-dir` target and report missing extension coverage rather than
silently changing every project configuration.

## 3. Extend Herdr focus using Pi's identity

The current resolver accepts only Codex and matches
`agent_session = {agent: "codex", kind: "id", value: session_id}`.
Adding Pi to that existing comparison would not match the live Pi panes.

Carry a bounded optional Pi session path through state, SSH decoding, and the
C# row/tile models. Keep the native session ID as a separate field. Match:

```text
Codex: agent=codex, identity.agent=codex, kind=id, value=native session ID
Pi:    agent=pi,    identity.agent=pi,    kind=path, value=exact session path
```

Allow Pi's ID fallback only when Herdr itself reports `kind: "id"`. Compare the
exact reported path on its own host; do not extract IDs from filenames, resolve
remote paths on the Mac, or truncate identity values. A session path is matching
data, never an executable path or permission to read a remote file.

Reuse the existing explicit local socket and remote-source bindings, including
the `clouddesk` binding for a Mac client attached through `herdr --remote`.
Retain the list/get/focus identity checks, stable terminal ID verification,
outer iTerm session UUID, timeouts, and ambiguity rejection.

This design uses no tab index. Pi still needs its own live test that reorders
both Herdr tabs and iTerm tabs, verifies the same native session was selected,
and restores the original arrangement.

## 4. Reuse display settings and install on both hosts

Add `pi` to the adapter registry, CLI selection, SSH client allowlist, client
captions, and pet-rule validation. Pi rows can then use the existing paged,
`recent`, `recent_open`, and `newest` views. Parents and children each count as
one row. Heartbeats and collection polls must not change recent ordering.

Continue using `~/.config/codex-mx-bridge/display.json`. The inspected
configuration's default cat and remote Pingu rule would apply to Pi; the
Claude-specific Dario rule would continue to apply to Claude.

After implementation, this fragment could select Pingu specifically for remote
Pi sessions using the existing rule format:

```json
{
  "pet_rules": [
    {"client": "pi", "location": "remote", "pet": "pingu"}
  ]
}
```

This is a fragment to merge with existing rules, not a replacement config.
Per-client, host, and individual-chat overrides, label switches, and FPS
settings should remain hot reloadable. Role-wide pet selection would require a
separate rule selector; it is not currently supported.

Update the installer to treat Pi as an extension-file target, not a Claude-style
JSON hook merge. Back up an existing target, recognize bridge-owned content,
record it in the installation manifest, and support idempotent install,
update, and removal. Check Pi's supported version and selected agent directory.

On the Mac, install the extension and updated bridge/plugin. On the cloud
desktop, upgrade the older bridge and install the extension with hooks/export
components only. Reuse the existing SSH collector; no additional network
listener is needed. Preserve other clients' hooks and Pi's packages, models,
roles, thinking levels, and Herdr configuration.

New sessions load the extension automatically. Existing sessions need Pi's
`/reload` at an idle boundary, or a later restart. Display-only settings continue
to reload without a Pi restart or plugin reinstall.

## Implementation sequence and acceptance

| Stage | Main changes | Required evidence |
| --- | --- | --- |
| Pi event/state contract | New extension and adapter; `adapters/common.py`, `state.py`, `cli.py` | Native session identity, parallel tools, UI waiting, retry/settlement, names, heartbeat, reload, and shutdown cases |
| Installation and remote transport | `install.py`, installer/updater scripts, `ssh.py` | Reinstall/removal preserve unrelated files; custom directories work; cloud export retains Pi identity and strips local control metadata |
| Display and focus | `ViewModel.cs`, `DisplayModel.cs`, `PetSelection.cs`, status mapping, `HerdrFocus.cs` | Pi captions and pets; separate child rows; exact Pi path matching; Codex/Claude/Kiro regressions |
| Activate and verify | Mac plugin plus both hosts' extensions | Real parent and child observations on each host; live button focus, both tab reorderings, SSH failure, closed pane, and layout restoration |

Use isolated Pi configurations and a local fake provider for native dispatch
tests before any live model run. Include a persistent child receiving another
task, a resumed child with a new launch ID, two sessions with the same name,
and a standalone child with no parent header. Test missing Python, state-lock
contention, timeouts, and a child exiting during an SSH refresh.

Run the existing Python and C# suites and the SDK plugin build once the code
changes are in place. Report fixture tests, native Pi dispatch, and physical
button verification separately.

## Evidence sources

Installed Pi API declarations and documentation:

```text
@earendil-works/pi-coding-agent@1.5.0
  dist/core/extensions/types.d.ts
  dist/core/session-manager.d.ts
  docs/extensions.md
https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/src/core/extensions/types.ts
```

Installed Pi Herdr Agents sources, with the launch source checked against the
published package's upstream commit:

```text
pi-herdr-agents@3.7.2
commit 5335202f87d69ae43d48553c92bb96f5b6c94d1e
  maestro/adapters/pi/launch.ts
  maestro/adapters/pi/launch-resume.ts
  maestro/adapters/pi/session.ts
  maestro/runtime/pi-run-session-types.ts
  pi-extension/subagents/launch-tools.ts
https://github.com/giuseppecrj/pi-herdr-agents/tree/5335202f87d69ae43d48553c92bb96f5b6c94d1e
```

The native `~/.pi/agent/extensions/herdr-agent-state.ts` files were identical
on both hosts. Live evidence came from `herdr agent list`, selected cloud child
environment fields, and session-header identity fields only.
