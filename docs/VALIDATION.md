# Validation record

Latest validation: 25 October 2026, Australia/Sydney.

## Per-chat pet selection — 25 October 2026

* 125 Python tests and 267 C# checks passed against the isolated feature source.
  New coverage includes selector validation, ordered rule precedence,
  local/remote and client isolation, child-agent keys, full remote aliases,
  short-name resolution, ambiguous revisions, separate frame data for different
  pets, loading limits, and the Python-to-C# settings contract.
* The Release build passed with zero warnings/errors against the real SDK.
  LogiPluginTool packed and verified the plugin. The package contains no
  downloaded pet sheets or imported frame packs.
* Clippit, Pingu, Leader Avatar and Dario were downloaded and imported locally.
  The repository includes installation instructions and geometry fixtures,
  rather than these art assets.
* Installed release `0.3.0-b155fbe5968a`. Configuration reloads acknowledged
  individual-chat selections in 0.309–0.571 seconds with the same service PID.
  A missing selected pack produced a `pet_errors` entry while the cat, Pingu
  and Dario packs remained loaded. The requested defaults were restored.

The final local settings retain the current cat, select Pingu for remote
sessions, and select Dario for Claude regardless of location. Eight FPS,
recent-chat view and caption settings were preserved.

No fresh button-image callback was observed during this verification;
`render-status.txt` still predated the update. Pack decoding, selection and
config reload were verified, but physical multi-pet rendering and LCD legibility
remain hardware acceptance checks.
Local receipt:
`~/.local/share/codex-mx-bridge/backups/pet-selection-verification-2026-10-25.json`.

## Display config directory — 25 October 2026

* 121 Python tests and 220 C# checks passed.
* New checks cover `.config` precedence, legacy fallback, invalid preferred
  settings, preserving existing values on the first write, private file
  permissions, and isolation of custom state directories.
* The release build passed with zero warnings/errors, and LogiPluginTool
  packed and verified the updated plugin.

The default settings path is now
`~/.config/codex-mx-bridge/display.json`. Pet assets and runtime state still
resolve from the state directory. The preview renderer uses the same settings
lookup as the CLI.

Installed release `0.3.0-a8a501347017`, then moved the existing display config
to the new directory with a private backup. The plugin detected the path
change without another restart. Status-caption off/on changes reloaded in
0.571/0.468 seconds with the same service PID, and every original setting was
restored. The old active config file was removed after backing it up.
The CLI and preview reader both found the new file and the existing cat pack.
Receipt: `~/.local/share/codex-mx-bridge/backups/config-directory-verification-2026-10-25.json`.

## Recent chat views and Marketplace investigation — 25 October 2026

* 118 Python tests passed, including creation-time persistence across resume
  and heartbeat, relative creation ages over SSH, old exporter compatibility,
  invalid remote timing, and all four config values.
* 211 C# checks passed: 27 view-model/contract, 19 sprite, 24 configurable label,
  27 chat view, 108 Herdr focus and 6 socket checks.
* The real SDK release build passed with zero warnings/errors.
  `LogiPluginTool` 6.1.4.22672 packed and verified the `.lplug4`.

The new view tests use more than nine rows and cover combined local/remote
ordering, finished versus ended-turn filtering, missing creation timestamps,
stable tie handling, diagnostic slots and preservation of source isolation.
A simulated reorder verifies that button focus retains the last rendered
chat identity until the next button image is rendered.

Installed release `0.3.0-dde662ecc3dd` using the updater. The running plugin
accepted `recent`, `recent_open`, `newest`, and the restored `paged` setting
in 0.836, 0.489, 0.572 and 0.474 seconds respectively, including CLI invocation.
The service PID remained unchanged across all four changes. The selected pet,
motion and caption settings were preserved, and a new 116 × 116 pet draw was
recorded after the restart. The local receipt is
`~/.local/share/codex-mx-bridge/backups/chat-view-reload-verification-2026-10-25.json`.
Physical ordering, paging and focus acceptance still need device observation.

The Marketplace investigation used current public Logitech documentation and
inspected the generated archive. The package verification passed despite
missing mandatory submission metadata described in the newer public guide;
it is not a Marketplace approval or complete submission-readiness result.
See [the publishing assessment](MARKETPLACE-PUBLISHING.md).

## Legacy Herdr rows and configurable labels — 25 October 2026

| Check | Observed result |
| --- | --- |
| `python3.15 scripts/test_all.py` | 113 Python tests; 27 view-model/contract, 19 sprite, 24 configurable label, 108 Herdr focus, and 6 socket checks passed |
| Release plugin build against `LogiPluginTool` 6.1.4.22672 `PluginApi.dll` | Passed, zero warnings and errors |
| Production resolver against live state and Herdr RPC | Slot 3 resolved by exact native session ID to `wP:p4`; slot 4 had no live identity match |
| `bash update.sh --no-downloads` | Installed release `0.3.0-08e6273ee6a1`, refreshed the three registered clients and restarted Logi Plugin Service |
| Plugin rendering after restart | `render-status.txt` recorded a successful 116 × 116 pet draw with the new plugin |
| Live `display.json` reload | Status caption off/on observed in 0.608/0.488 seconds, including CLI invocation, with the same service PID |

The legacy focus checks cover rows without a socket, uniqueness across bound
servers, unreachable servers and explicit-socket isolation. Existing terminal
preflight, identity recheck and focus response checks remain in place.
The live mapping probe made only read requests and did not select a pane.

Label checks cover independent captions, pet-only layout, name overrides,
local/remote/client isolation, optional name catalog loading and renaming,
invalid settings, and preserving labels across other display changes. CLI
tests verify that display changes do not create or rewrite agent state.
The installed plugin reported each live setting in `display-status.txt`.
The selected pet, animation rate and motion setting were preserved; all
captions were restored to enabled after the check. The reload receipt is
stored locally under the install prefix at
`backups/label-reload-verification-2026-10-25.json`.

The physical button press and LCD appearance remain unverified; successful
rendering in the plugin does not establish legibility on the device.

## Claude Code and Kiro hooks — 25 October 2026

Validated on macOS with Python 3.15, .NET 8, native Claude Code 2.1.308
(vendor installation 2.1.308.1314), and Kiro CLI 2.34.0.

| Check | Observed result |
| --- | --- |
| `python3.15 scripts/test_all.py` | 110 Python tests; 27 view-model/contract, 19 sprite, 88 Herdr focus, and 6 socket checks passed |
| Release plugin build against `LogiPluginTool` 6.1.4.22672 `PluginApi.dll` | Passed, zero warnings and errors |
| Native Claude lifecycle smoke | Real `SessionStart`, `UserPromptSubmit`, `Stop`, and `SessionEnd` dispatch; one loopback model request; one closed Claude row |
| Kiro `agent validate --path` on generated temporary profiles | Both legacy object and current array hook formats accepted |
| Isolated Kiro `agent upgrade --dry-run` after changing only bridge hooks | Existing migration metadata remained valid; permissions were preserved |
| Bash syntax and `git diff --check` | Passed |

The automated tests cover cross-client/session/child identity, old-turn events,
stop continuation, shared-state concurrent writers, client-specific silent
failure, missing runtimes, stalled stdin, SSH metadata, display labels, and
Codex-only Herdr focus. Real staged installs/upgrades run in temporary directories
with stubbed client version/validation commands. They preserve other handlers
and access rules, retain registered configuration paths, and leave Codex settings
alone when only Claude/Kiro are selected.

The optional Claude smoke test uses a temporary config, tools disabled, no MCP
servers, a fake API key, and a deterministic loopback Messages API fixture.
macOS `sandbox-exec` denies outbound network access except to that fixture.
It checks the real CLI dispatch and verifies that prompt/response text is absent
from bridge state. Run it with the native executable, not a vendor launcher that
may configure IDE settings:

```sh
python3.15 tests/claude_hook_smoke.py --claude-bin /absolute/path/to/native/claude
```

Kiro's native hook dispatch during a real chat is not yet observed. Its profile
validation, exact generated shell commands, and payload handling have separate
coverage. Claude tool, permission, compaction, child, and failure events have
fixture coverage but were not triggered by the native lifecycle smoke.
Live hook activation, new-client LCD rendering, and button focus remain runtime
checks after following [the setup guide](CLAUDE-KIRO.md).

## Focus script loading fix — 25 October 2026

The first live button attempt after the upgrade reported a null `path1` error.
The focus action derived its script path from `Assembly.Location`, which can
be empty when Logi loads the assembly from bytes. The script is now an embedded
resource, passed to `osascript` through stdin with target values in argv.

* Release build against the real Logi SDK passed with zero warnings/errors.
* `scripts/test_all.py` passed 75 Python tests and 20 view-model/contract,
  18 sprite, 84 Herdr focus, and 6 socket checks.
* A regression loads an assembly from bytes, verifies its location is empty,
  and successfully reads the embedded script.
* `--probe-script` checked the actual packaged plugin, then invoked its
  launcher with harmless AppleScript to verify stdin and all three arguments.
  No user window was selected.

The corrected plugin still needs installation and a live focus check. Existing
Codex processes must load the updated hooks to supply their Herdr socket.

## Upgrade helper update — 25 October 2026

`bash update.sh` upgrades an existing installation from the current checkout.
The updater and installer changes passed:

* 75 Python tests, plus 20 C# view-model/contract, 18 sprite, 82 Herdr focus,
  and 6 Unix socket checks through `scripts/test_all.py`.
* Bash syntax validation and a real `update.sh --dry-run --no-downloads`
  against the existing Mac installation. It selected the cached .NET 8
  `LogiPluginTool` SDK and made no installation or service changes.
* A real hooks-only upgrade in temporary directories, preserving existing
  hooks, agent state, display settings, and Herdr bindings.
* Simulated Mac upgrade/reload checks for SDK selection, retained install
  paths, manifest backup, binding validation, build failure, process respawn,
  restart timeout, and deferred restart.
* Read-only verification that the exact current-user process selector matches
  the running Logi Plugin Service.

The user subsequently ran the Mac upgrade successfully, installing release
`0.3.0-b98b88e0486b`, saving the Herdr binding, and restarting the service.
Read-only inspection confirmed the updated plugin link and live pet rendering.
The first focus attempt exposed the script-loading issue addressed above.

## Local Herdr focus update — 25 October 2026

Validated on macOS using the installed Python 3.15 environment, .NET 8, and
the real `LogiPluginTool` 6.1.4.22672 SDK:

| Check | Observed result |
| --- | --- |
| `python3.15 scripts/test_all.py` | 62 Python tests; 20 C# view-model/contract, 18 sprite, 82 Herdr focus, and 6 Unix socket checks passed |
| Release plugin build against the SDK | Passed, 0 warnings, 0 errors |
| `osacompile` on `plugin/package/focus.applescript` | Passed |
| C# `--probe-herdr` against the running local server | Read-only `agent.list` succeeded with 9 agents |
| Live Herdr contract inspection | CLI 0.9.5 schema; server snapshot reported 0.9.3/protocol 22; `agent.list` and `agent.get` response shapes verified |

New checks cover explicit terminal bindings, replacement/removal, old-row
metadata refresh, remote socket stripping, duplicate/missing native identities,
reused panes, missing Mac terminals, rejected/unconfirmed focus, fragmented
responses, response-ID mismatch, disconnects, size limits, and cancellation.

No live `agent.focus` or iTerm selection was performed. Activating the feature
requires updating the installed hooks/plugin and binding the intended outer
terminal. An on-device press with that Herdr client attached, including the
session-wide effects on other clients, remains unverified. See
[Herdr focus setup](HERDR-FOCUS.md).

## Observed locally

Environment: Windows build machine; stable CPython 3.15.1, .NET SDK 8.0.202,
Codex CLI 0.163.0-alpha.10.2. The target runtime is macOS/iTerm2; Linux runs
the remote hook writer and export side.

| Check | Observed result |
| --- | --- |
| `python3.15 scripts/test_all.py` with Pillow 13.0.0 | 52 Python tests, 16 C# view-model/contract checks, and 18 sprite display checks passed |
| `python3.15 tests/codex_hook_smoke.py` | Real CLI emitted SessionStart, UserPromptSubmit, Stop, SessionEnd; bridge state updated |
| `python3.15 scripts/build_plugin.py --sdk <real PluginApi.dll>` | Build succeeded, 0 warnings, 0 errors |
| `logiplugintool pack plugin/bin/Release/package CodexMx_0_3_0.lplug4` | Passed |
| `logiplugintool verify CodexMx_0_3_0.lplug4` | Passed |
| `bash -n install.sh` | Shell syntax check passed |

The original 0.1.0 validation used Python 3.11.15. Version 0.2.0 was retested on
stable 3.15.1 and now pins Python 3.15 in metadata, runtime checks, installer, and
the CI template. CPython was downloaded with a private uv 0.13.5 installation;
the user's existing Python/uv installation was not changed.

Version 0.3.0 adds optional Pillow 13.0.0 importer coverage on stable Python
3.15.1. Tests use transparent geometry fixtures, not redistributed Codex pet art.
They exercise v1/v2 standard row extraction, explicit alternate layouts,
alpha/registration, blank/opaque/oversize rejection, selection, motion-off,
safe paths and corrupt configuration recovery. C# checks cover status mapping,
bounded timing, loop wrap, still stale/offline, and manifest/path validation.
The renderer is compiled against the real SDK; native image decoding and LCD
motion still require the host/hardware. Core CLI smoke also runs without Pillow
to verify that the optional importer does not affect hooks.

Installer coverage executes the real isolated Python 3.15 venv and hook check
in temporary directories. It verifies repeated installation, spaced paths,
Herdr preservation, TOML config backups/semantic equivalence, previous plugin
backup, and no mutation on validation failures or dry-run. The Mac build/link
branch is tested with a simulated home and compiler output, not with a macOS
host. Python bootstrap downloads, Options+ vendor setup, and the full Mac install
still need on-device validation.

The API assembly came from the official NuGet `LogiPluginTool` package
`6.1.4.22672`, not from a test double. The package verifier checked the resulting
Logitech package structure; this does not constitute a physical device test.
The proprietary API assembly is not included in project downloads.

The real-CLI smoke test creates a temporary Codex home, installs test-owned
hooks, and points a custom provider at an HTTP fixture bound to loopback. It
does not invoke an external model, inspect the user's credentials, or alter
their Codex configuration. It verifies real dispatch of the four named hooks,
not just a synthetic payload parser. Other documented hooks use fixture/unit
coverage here rather than a live Codex trigger.

Python coverage includes:

* lifecycle transitions, compaction, subagent identity, and old tool results;
* resume into a new direct/Herdr attachment, dropping obsolete focus metadata;
* concurrent subprocess writers and atomic file/revision handling;
* advisory hook failure with valid JSON and no prompt/command content retained;
* optional launcher pass-through, nonzero child exit, heartbeat state;
* non-destructive Herdr hook merging, idempotence, backup, and removal;
* SSH command quoting/host trust, bounded decoding, relative clocks, and cache
  retention on simulated disconnect.

C# checks cover status expiry, closed rows, remote disconnect/collector loss,
focus suppression, pagination, schema/version handling, and a state file
written by the Python implementation.

## CI and remaining runtime checks

The repository includes `ci/github-actions.yml.example`, a GitHub Actions
matrix template for macOS, Ubuntu, and Windows. It has not been installed or run:
the GitHub sign-in available during delivery can push source but lacks the
`workflow` scope needed to publish `.github/workflows/` files. To enable CI later,
use an appropriately authorized sign-in and copy the template to
`.github/workflows/test.yml`. No cross-platform CI pass is claimed. Live Codex
smoke and Logitech host/device checks remain separate from portable tests.

These have **not** been observed in this build environment:

* Loading/rendering the plugin in macOS Logi Plugin Service and physical LCDs.
* macOS Automation permission and iTerm2 window/tab/pane focus.
* Interactive PermissionRequest, Interrupt, compaction, and subagent hooks.
* Actual SSH authentication/polling against the user's Linux desktop.
* Herdr session restore, display detection with a Python launcher, and both
  Herdr remote attachment paths on the user's installed version.

Use the README's acceptance checks and remote setup guide to verify those.
The separate Herdr assessment is a source/documentation audit, not a deployed
Herdr adapter or a live compatibility claim.
