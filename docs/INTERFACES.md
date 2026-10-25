# Verified interfaces and limitations

Checked 24 October 2026 against primary documentation and an installed CLI.
The earlier conversation is background context, not API evidence.

## Codex CLI

The release behavior reference is OpenAI's [Hooks documentation](https://learn.chatgpt.com/docs/hooks).
Our adapter uses its command hooks, stdin object, `hooks.json` group structure,
and these event names:

| Hook | Bridge result |
| --- | --- |
| `SessionStart` | READY; compact starts preserve existing status |
| `UserPromptSubmit` | WORKING |
| `PreToolUse` | TOOL |
| `PermissionRequest` | APPROVAL? |
| `PostToolUse` | WORKING |
| `PreCompact`, `PostCompact` | COMPACT, WORKING |
| `SubagentStart`, `SubagentStop` | Separate child row, WORKING or STOPPED |
| `Stop`, `Interrupt`, `SessionEnd` | TURN STOP, INTERRUPTED, CLOSED |

Only IDs, event names and the cwd basename are retained. Shared input keys are
`session_id`, `hook_event_name`, and `cwd`; turn matching uses `turn_id`, child
identity uses `agent_id`/`agent_type`, and compact handling reads `source`.
Subagent hooks share the parent's `session_id`, so a child key includes `agent_id`.
No transcript content is read. The adapter emits `{}` and exits 0; it makes no
permission decision and cannot block a Codex operation.

The installer writes user-level `$CODEX_HOME/hooks.json` and preserves other
handlers. Codex's `/hooks` trust review still applies. A current CLI is required;
we do not invent a minimum version from current documentation or main-branch
schemas. Observed live smoke coverage is recorded in [validation](VALIDATION.md).

### Deliberate limits

* `Stop` occurs before all continuation decisions are final. It does not certify
  successful completion. `SubagentStop` has the same continuation caveat.
* There is no approval-resolved hook in the used interface. A permission hook
  may be resolved by policy or another handler before a visible UI prompt.
  `APPROVAL?` remains until another observed event changes it. Concurrent tools
  can overwrite each other's transient display state.
* Tool events do not provide a stable child identity in their common schema;
  the main row reflects session activity, while child rows show start/stop only.
* Hosted tools and some specialized paths do not emit ordinary tool hooks.
  Tool errors have heterogeneous output shapes. We do not infer success/failure
  from arbitrary tool output, nor implement undocumented `PostToolUseFailure`.
* There is no universal hook for every assistant question, idle input prompt,
  model token, retry, API failure, or loss of network. Process liveness is an
  optional wrapper observation rather than a Codex lifecycle API.
* Hook execution can be skipped, denied by policy, time out, or fail after a
  crash. Unknown/stale states are unavoidable without another telemetry source.
* Other hooks can run concurrently. A file lock serializes our writers; it
  cannot reconstruct causality between genuinely concurrent events. Turn IDs
  prevent known older tool results from reviving an ended/current turn.
* `SessionEnd` does not imply that merely detaching a client stopped its server.
  Abrupt process termination may skip it; launcher exits or expiry cover that gap.

The older [`notify` integration](https://learn.chatgpt.com/docs/config-file/config-advanced)
supports `agent-turn-complete`, supplied as a JSON command-line argument. It is
not used here because it alone cannot supply working, tool, and permission
states. TUI notifications such as `approval-requested` are terminal/UI signals,
not additional external `notify` events. No `on_turn_start`/`on_turn_end` config
keys or Claude-specific `Notification` hook are assumed.

## Logitech Actions SDK

This project uses the C# API that runs inside Logi Plugin Service. The assembly
and namespace retain the `Loupedeck` name; that is normal for the official API.

| Used capability | Evidence |
| --- | --- |
| `Plugin`, `ClientApplication`, .NET 8 and macOS development | [C# introduction](https://logitech.github.io/actions-sdk-docs/csharp/plugin-development/introduction/) |
| `PluginDynamicCommand`, `AddParameter`, `GetCommandDisplayName` | [Parameterized command tutorial](https://logitech.github.io/actions-sdk-docs/csharp/tutorial/add-a-command-with-a-parameter/) |
| `GetCommandImage`, `ActionImageChanged`, `BitmapBuilder.DrawText` | [Button image tutorial](https://logitech.github.io/actions-sdk-docs/csharp/tutorial/change-a-button-image/) |
| Background redraws | [Official Snake example](https://github.com/Logitech/actions-sdk/tree/master/SnakePlugin/src) |
| Dial adjustment methods | [Official Counter example](https://github.com/Logitech/actions-sdk/blob/master/DemoPlugin/DemoPlugin/CounterAdjustment.cs) |
| `.lplug4`, metadata, `pack` and `verify` | [Distribution guide](https://logitech.github.io/actions-sdk-docs/csharp/plugin-development/distributing-the-plugin/) |

The source was compiled against the real API assembly bundled with
`LogiPluginTool 6.1.4.22672`. That assembly exposes protected `OnLoad`/`OnUnload`
for actions, which this project uses; it does not assume that examples targeting
newer SDK versions can be copied unchanged. The examined official examples repo
was commit `d8bcb3432dfe95ff34e6bcd2a891d649ded319cc`.

The host is responsible for device I/O and redraw scheduling. We request redraw
after a changed display snapshot; we claim neither a guaranteed hardware frame
rate nor animation performance. The source provides action mappings for the
user to assign in Options+, not a replacement device profile. No haptics,
marketplace submission, hardware reverse engineering, or Node SDK dependency
is required. No claim that the Node SDK is Windows-only is made.

The optional [pet display](PET-DISPLAY.md) uses the same documented image/redraw
API, with cached PNG frames and bounded local animation ticks. It does not use
an animated-image or pet API in Logitech. Local sheet import (Pillow 13) is
separate from hook/SSH delivery. No desktop pet export or selected-pet state API
was verified; compatible local v1/v2 sheets or an explicit layout are required.

## iTerm2

Focus uses the documented AppleScript session `unique id`/`tty` and session,
tab, and window `select` operations from the [iTerm2 scripting guide](https://iterm2.com/documentation-scripting.html).
The static script is embedded in the plugin assembly and sent to `osascript`
on stdin, so it also works when the host loads the assembly from memory.
Values arrive as process arguments rather than source interpolation.
The common `w...:UUID` environment format is normalized by taking
the suffix; this is an integration convention that still needs Mac validation.
An explicit UUID has priority over tty so a reused tty cannot redirect a UUID
target. A tty-only target can be reused by the OS after a pane closes; prefer
the UUID path and verify behavior before relying on tty-only focus.

AppleScript is in maintenance/deprecated status in iTerm2 documentation. It
remains the small dependency-free compatibility path here; an iTerm2 Python API
adapter would be a future alternative. macOS Automation consent, direct local
pane identity and a currently running iTerm session are prerequisites. No GUI
keystroke automation, terminal command injection, Codex chat focus API, or
automatic Herdr-client discovery is assumed. [Local Herdr focus](HERDR-FOCUS.md)
uses an explicit outer iTerm2 binding and the public Herdr agent API.

## Transport and local trust

The file schema belongs to this project, not OpenAI or Logitech. It is versioned
as `schema_version: 1`. `state.json` updates use an advisory lock, temporary file,
flush, and atomic rename on a **local filesystem**. Network-mounted homes and
power-loss durability are not guaranteed. The project state directory is mode
0700 and newly written JSON is mode 0600 on macOS/Linux. This is same-user local
integration, not a boundary against malicious processes running as that user.

The runtime is pinned to stable Python 3.15 (`.python-version`, project metadata,
entry-point check, installer venv, and CI template). The shell bootstrap uses a
private [uv install](https://docs.astral.sh/uv/reference/installer/) and
[managed Python](https://docs.astral.sh/uv/guides/install-python/) when needed.
An older interpreter still returns advisory `{}` for a hook invocation, but
normal bridge commands reject it. Installed hooks always name the 3.15 venv
interpreter explicitly.

`install.sh` and `scripts/install_local.py` are this project's installer, not
a Codex API. They back up and merge hook settings, and enable explicitly disabled
user hooks with a verified TOML edit. They do not mark hooks trusted. The Mac
build can obtain a private .NET 8 SDK with Microsoft's
[official install script](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-install-script).
Options+ can optionally be installed through its verified
[Homebrew cask](https://formulae.brew.sh/cask/logi-options%2B). App permissions,
vendor setup, and device mappings still require the normal host UI.

The SSH collector uses documented OpenSSH command-line conventions and a
sanitized versioned export. It preserves SSH host-key checks and noninteractive
authentication. Polling is eventually consistent; there is no event replay,
inbound service, remote control, or promise of exact status during disconnection.

## Herdr

For local button focus, hooks record `HERDR_SOCKET_PATH` only when
`HERDR_ENV=1` and no `SSH_CONNECTION` is present. The plugin uses the configured
socket's `agent.list`, `agent.get`, and `agent.focus` methods with
newline-delimited JSON request/response IDs. It matches the native Codex
session identity and rechecks the stable terminal ID immediately before focus.
These are the only socket methods called; no terminal content is requested.
Responses are capped at 1 MiB and the entire focus action at eight seconds.
The Mac binding file is separate from exported state; socket paths are stripped
from SSH exports and remote rows never become local focus targets.

The bridge coexists with Herdr rather than reading its internal files. Herdr's
[integration docs](https://herdr.dev/docs/integrations/) explain the Codex hook
and its distinction from screen-detected state. The [remote workflow](https://herdr.dev/docs/how-to-work/)
keeps agents on the server; hooks must be installed there. The independent
[assessment](HERDR-EXTENSION-ASSESSMENT.md) audits possible richer Herdr APIs.
