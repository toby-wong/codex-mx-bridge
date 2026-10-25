# Claude, Kiro, and MeshClaw hook integration plan

Status: Claude and Kiro implementation is available; see
[setup](CLAUDE-KIRO.md) and [validation](VALIDATION.md). MeshClaw/Kiro Crew work
remains proposed. The design below records the original plan.
Investigated on 2026-10-25 against bridge commit `0c0a295`.

Add client-specific hook adapters feeding the existing bridge state and pet
display. Deliver Claude Code first, the installed Kiro CLI 2.x next, then
MeshClaw after establishing its installed hook contract. Kiro Crew is a separate
compatibility target: its current source does not prove compatibility with an
older MeshClaw installation.

## Compatibility findings

| Target | Evidence checked | Initial approach |
|---|---|---|
| Claude Code | Installed CLI reports `2.1.308.1314`; current official hook reference [1] | Command hooks merged into the selected Claude settings file. |
| Kiro CLI | Installed CLI reports `2.34.0`; official migration guide documents the 2.x object format [2] | Hooks in explicitly selected agent configurations. Do not install V3-only files into a 2.x setup. |
| Kiro CLI V3 | Current official configuration and trigger documentation [2–4] | A later version-selected installer can generate standalone hook files. No CLI upgrade is part of this work. |
| MeshClaw | Installed `MeshClaw-beta.app` metadata reports `3.3.5` | Verify that build's payloads and configuration before enabling an adapter. |
| Kiro Crew | Public source at `d612350b692f5af02786ddc88564f52ec50a6d78`; no `kirocrew` executable found on PATH [5–7] | Use Crew's gateway hook contract when that product is present. Do not treat MeshClaw as an alias without a compatibility check. |

These checks establish an implementation direction, not successful live dispatch.
No Claude, Kiro, or MeshClaw lifecycle smoke test has run.

## Shared ingestion

Keep Python 3.15, the atomic state file, SSH export, and the existing Logitech
plugin. Add a small adapter boundary before state transitions:

```text
client command hook
  -> bounded JSON input
  -> client adapter: identity + observed event + safe display metadata
  -> shared state transition
  -> existing state.json / SSH export
  -> text tiles and pet animation
```

Proposed commands, not implemented yet:

```sh
bridge.py hook --client claude
bridge.py hook --client kiro
bridge.py hook --client meshclaw
bridge.py hook --client kirocrew
bridge.py install-hooks --client claude
bridge.py install-hooks --client kiro --agent-config /absolute/path/agent.json
```

An omitted `--client` continues to mean Codex. Existing commands, state paths,
environment variables, and Codex hook definitions remain compatible.

The normalized event contains only client, source instance, session identity,
optional child identity, event, optional turn identity, and a bounded project
label. Adapters discard prompt text, tool arguments/results, transcript paths,
assistant responses, and arbitrary extra fields before persistence.

Use `(client, source_instance, session_id, child_id)` as the identity tuple.
Generate bounded keys for new clients from the complete validated tuple; reject
oversize IDs instead of truncating them into collisions. Preserve existing Codex
keys and treat rows without a client field as Codex. Identity lookup must also
check the client, rather than relying only on a key prefix.

Add optional client metadata within state schema 1. Update the SSH decoder's
allowlist and the plugin model together. Display a short client label alongside
the existing project/host label. The pet continues to use the shared status;
there is no need for new artwork or a rendering rewrite.

## Claude adapter

Claude's documented payload supplies `session_id`, optional `prompt_id`, and
`agent_id` for child activity. Tool events inside a child must update that child,
not its parent. Normalize `prompt_id` to the bridge's turn identity when present.
Settings-based hooks cover child tool events too. [1]

| Claude event | Proposed bridge observation |
|---|---|
| `SessionStart` / `SessionEnd` | `READY` / `CLOSED` |
| `UserPromptSubmit` | `WORKING` |
| `PreToolUse` / `PostToolUse` | `TOOL` / `WORKING` |
| `PermissionRequest` | `APPROVAL?` |
| `PostToolUseFailure` | `WORKING`; a failed tool can be retried |
| `PreCompact` / `PostCompact` | `COMPACT` / `WORKING` |
| `SubagentStart` / `SubagentStop` | Child `WORKING` / `STOPPED` |
| `Stop` | `TURN STOP` |
| `StopFailure` | New `TURN ERROR`, including an explicit display/SSH mapping |

`Stop` is an observed boundary: another hook can cause continuation. A tool
failure does not establish overall failure. Do not invent a general Claude
`Interrupt` event or infer successful completion from notification prose. [1]

Install into the effective user settings path, respecting `CLAUDE_CONFIG_DIR`
or an explicit settings path; support project-local settings as an explicit
scope. Confirm path resolution on the installed build. Reuse the existing
backup/merge approach while preserving all unrelated settings and hooks.

Use bounded synchronous command hooks so background writes do not introduce
avoidable event reordering. Use the documented advisory failure setting where
supported, and emit empty stdout with exit 0. Existing Codex hooks retain their
`{}` response. Diagnostics belong in the bridge's private directory.

## Kiro adapter

Kiro 2.x embeds a hook object in an agent configuration; V3 supports inline
arrays and standalone files. These are different installer formats. The
documented lifecycle names map as follows. [2, 3]

| Kiro 2.x event | V3 equivalent | Proposed bridge observation |
|---|---|---|
| `agentSpawn` | `SessionStart` | `READY` |
| `userPromptSubmit` | `UserPromptSubmit` | `WORKING` |
| `preToolUse` | `PreToolUse` | `TOOL` |
| `postToolUse` | `PostToolUse` | `WORKING` |
| `stop` | `Stop` | `TURN STOP` |
| No assumed equivalent | `SessionEnd`, when verified | `CLOSED` |

Use the native session ID. Do not synthesize a session from the current
directory, agent profile name, or the short-lived hook subprocess PID. Check
which IDs the installed CLI supplies on every registered event before claiming
support. No independent permission-wait or subagent lifecycle coverage is
promised by this initial five-event integration.

Install into selected user-owned agent profiles and preserve their tools,
resources, permissions, and existing hooks. Do not rewrite every discovered
profile or Crew-generated profiles. For V3, prefer a dedicated bridge-owned
file in the requested hook scope. Resolve timeout units and caching fields
against the selected format; disable hook-result caching for status events.

Return empty stdout and exit 0, including failures. Kiro can inject hook stdout
into context, and some Stop failure/output paths can request another turn.
The display integration must not produce those decisions. [3, 4]

Kiro's documented examples do not establish a reliable turn ID for every event.
Keep the existing Codex late-event rules scoped to Codex. For Kiro, validate
synchronous dispatch ordering and Stop-hook continuation before deciding which
post-Stop events can resume activity. When session exit is not observable, use
the existing optional launcher for process exit or let the row expire as
`STALE`; silence does not mean completion.

## MeshClaw and Kiro Crew

Start with a compatibility probe for MeshClaw beta 3.3.5. Obtain its matching
source/configuration contract and capture synthetic event fixtures containing
only event names and identity fields. Check session identity across two
concurrent chats and a child task. The current Crew contract below is a
candidate, not evidence that the installed MeshClaw build supports it.

Current Crew gateway hooks expose `session_key`, and child events can include
`subagent_id` and `parent_session_key`. Use the firing session's own key, scoped
to an explicit gateway instance. Only the child ID establishes that an event
came from a child; a parent reference alone is insufficient. [5, 6]

The first Crew registration should contain:

| Gateway event | Proposed bridge observation |
|---|---|
| `AgentSpawn` | `READY` |
| `UserPromptSubmit` | `WORKING` |
| `PostToolUse` | `WORKING` |
| `Stop` | `TURN STOP` |

Exclude Crew `PreToolUse` from the initial display registration. On its gating
path, a crash, missing executable, or timeout can deny a tool call; current
source documents no per-hook advisory opt-out. Catching Python exceptions does
not protect against all of those failures. This MVP therefore does not claim
accurate Crew `TOOL` or `APPROVAL?` states. [5, 7]

Use the gateway's supported hook store/API for the verified version. Current
Crew documents `~/.kiro/crew/hooks.json`, but do not apply that path or schema
to MeshClaw without checking. Gateway hooks also receive a restricted
environment: use absolute executables and an explicit bridge state directory.
Never attach a gateway session to an inherited terminal identifier. [5, 6]

Do not enable both gateway hooks and Kiro CLI hooks for the same managed
session. Prefer gateway identity there; keep standalone Kiro installation
profile-scoped. A future global Kiro installation needs a verified nested-run
filter or exact identity correlation, not deduplication by project directory.

If the MeshClaw build lacks per-session identity, record native hook support as
unavailable for that build. A separate collector is an option only after
verifying a metadata-only status interface. Do not fabricate one combined row,
scrape transcripts, migrate installations, or modify the application bundle.

## Delivery sequence

| Step | Files/work | Acceptance |
|---|---|---|
| 1. Shared boundary and Claude | Add `mxbridge/adapters/`; update `bridge.py`, `mxbridge/cli.py`, `state.py`, `install.py`; extend SSH and plugin client/status fields. | Existing Codex behavior passes unchanged; concurrent Claude parent/child rows and Claude/Codex IDs stay separate. |
| 2. Installed Kiro 2.x | Kiro normalizer, selected-profile installer, version detection, fixtures from 2.34.0. Add V3 generation only with its own validation. | A real isolated CLI dispatch reaches the intended hook; existing profile settings survive install/reinstall/remove. |
| 3. MeshClaw compatibility and adapter | Establish beta payload contract; implement a separate MeshClaw adapter if supported. Keep current Crew fixtures/version support explicit. | Concurrent sessions stay distinct; display failure cannot affect an agent's tool permission; unsupported builds get a precise diagnostic. |
| 4. Packaging and device checks | Extend `scripts/install_local.py`, installation metadata, docs, and targeted tests. | Staged release works independently of the checkout; local and Linux/SSH observations reach text and pet modes. |

The full installer must become client-selective: it currently assumes Codex
configuration, enablement, and restart instructions. Installing a Claude-only
integration must not run Codex enablement steps.

Use format-valid ownership markers: Claude supports the existing style of
handler marker; Kiro/Crew require their own ownership mechanism, such as a
dedicated wrapper path tracked in the install manifest. Do not add unsupported
JSON fields. Preview first, back up touched files, detect concurrent edits,
replace only bridge-owned entries, and provide removal per client. Verify each
staged entrypoint before updating live configuration.

## Validation required before enabling

1. **Identity and transitions:** same session ID across clients; simultaneous
   parent/child events; resume; compaction; duplicate input; delayed tool
   results; Stop followed by a continuation; session restart/identity reuse.
2. **Agent noninterference:** malformed/oversize input, missing IDs, state lock
   contention, unwritable state, wrong interpreter, missing installed command,
   and command timeout. Check the actual client's output/exit behavior as well
   as the Python handler. No decisions or prompt text may be emitted.
3. **Configuration:** existing unrelated hooks/settings retained; installation
   idempotent; removal scoped; concurrent edits rejected; version-specific
   schema and timeout units accepted by the installed client.
4. **Privacy and transport:** only approved metadata persists; new fields survive
   SSH sanitization; old schema-1 rows still load; remote/gateway rows have no
   local focus target; expired observations stop animating.
5. **Visible behavior:** a real hook dispatch updates the expected button and pet
   animation; child completion leaves its parent unchanged; working, stopped,
   error, and stale states are distinguishable.

Use sanitized fixtures for unit coverage and isolated client configurations for
dispatch checks. Reuse the existing test runner. Report synthetic parser tests,
real client dispatch, and physical-device verification separately; passing one
does not establish the others. Add per-client last-received/last-error metadata
so missing events can be distinguished from rendering failures without logging
payloads.

## Sources

Public references were checked on 2026-10-25. The installed versions above come
from local version commands or application bundle metadata. Current documentation
must be checked against each installed client before generating configuration.

- [1] Claude Code hook reference:
  `https://code.claude.com/docs/en/hooks`
- [2] Kiro CLI 2.x to V3 hook migration:
  `https://kiro.dev/docs/cli/v3/hooks-migration/`
- [3] Kiro hook triggers and payload examples:
  `https://kiro.dev/docs/hooks/types/`
- [4] Kiro hook actions and output handling:
  `https://kiro.dev/docs/hooks/actions/`
- [5] Kiro Crew gateway hook documentation, pinned source:
  `https://github.com/kirodotdev/KiroCrew/blob/d612350b692f5af02786ddc88564f52ec50a6d78/src/kiro_crew/docs/steering-and-hooks.md`
- [6] Kiro Crew event construction and script dispatch, pinned source:
  `https://github.com/kirodotdev/KiroCrew/blob/d612350b692f5af02786ddc88564f52ec50a6d78/src/kiro_crew/hook_runtime/script_hooks.py`
- [7] Kiro Crew hook exit contract, pinned source:
  `https://github.com/kirodotdev/KiroCrew/blob/d612350b692f5af02786ddc88564f52ec50a6d78/docs/reference/kiro-cli/hooks.md`

Related bridge documents:
[current interfaces](INTERFACES.md),
[validation coverage](VALIDATION.md), and
[Herdr assessment](HERDR-EXTENSION-ASSESSMENT.md).
