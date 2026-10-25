# Validation record

Date: 24 October 2026, Australia/Sydney.

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
