# Validation record

Date: 24 October 2026, Australia/Sydney.

## Observed locally

Environment: Windows build machine; Python 3.11.15, .NET SDK 8.0.202,
Codex CLI 0.163.0-alpha.10.2. The target runtime is macOS/iTerm2; Linux runs
the remote hook writer and export side.

| Check | Observed result |
| --- | --- |
| `python scripts/test_all.py` | 24 Python tests and 16 C# view-model/contract checks passed |
| `python tests/codex_hook_smoke.py` | Real CLI emitted SessionStart, UserPromptSubmit, Stop, SessionEnd; bridge state updated |
| `python scripts/build_plugin.py --sdk <real PluginApi.dll>` | Build succeeded, 0 warnings, 0 errors |
| `logiplugintool pack plugin/bin/Release/package CodexMx_0_1_0.lplug4` | Passed |
| `logiplugintool verify CodexMx_0_1_0.lplug4` | Passed |

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
