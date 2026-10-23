# Codex MX Bridge

Display Codex CLI lifecycle events on Logitech MX Creative Console. Runs beside
Herdr and can collect Linux-hosted agents over SSH. This is a working source
implementation with portable tests and an SDK-validated plugin package; physical
hardware and macOS integration still need the acceptance checks below.

Repository: [toby-wong/codex-mx-bridge](https://github.com/toby-wong/codex-mx-bridge)
(private). Version 0.1.0. Documentation verified 24 October 2026.

## What is included

* Python 3.10+ bridge using only the standard library: hook handler, atomic local
  state, optional process launcher, hook installer, SSH collector, and simulator.
* C# .NET 8 plugin built against the official Logi Actions SDK `PluginApi.dll`.
  Nine slot actions, a page adjustment for the dial, and a next-page button.
* Direct iTerm2 pane focus on a button press. Herdr and remote rows deliberately
  have no focus target in this version.
* Unit/integration tests, a real-CLI offline hook smoke test, and build/pack tools.
  A three-platform CI template is supplied in `ci/`; enabling it requires GitHub
  workflow permission, which the publishing sign-in did not have.
* [Verified interfaces and limitations](docs/INTERFACES.md),
  [SSH and Herdr setup](docs/REMOTE-AND-HERDR.md),
  [test evidence](docs/VALIDATION.md), and a separate
  [Herdr extension assessment](docs/HERDR-EXTENSION-ASSESSMENT.md).

No OpenAI API key is needed by the bridge. Codex retains its own normal login.
No Codex internal database, transcript parser, terminal screen scraper, or
undocumented Logitech socket is used.

## How it works

```text
Mac Codex CLI hooks ----> private state.json ----> Logi Actions C# plugin
                                                    | nine LCD actions
Linux Codex CLI hooks --> Linux state.json            | dial changes page
                                 |                   v
                         OpenSSH export <---- Mac collector
```

The plugin reads the Mac state file every 500 ms. Local hooks finish immediately
after a short locked write. The SSH collector normally polls every three seconds;
one collector runs per Linux host. Local collection needs no background server.

State lives at `~/.local/state/codex-mx-bridge/state.json` on both systems.
It retains a project basename or explicit label, IDs, event names, timestamps,
and direct local terminal identifiers. Prompt text, command arguments, tool
results, and assistant messages are discarded. Remote exports remove terminal
identifiers and do not recursively export other remote hosts.

## macOS setup

1. Put the complete project in a stable directory. Hook commands store an
   absolute path; moving it later requires reinstalling/retrusting the hooks.

   ```sh
   git clone https://github.com/toby-wong/codex-mx-bridge.git
   cd codex-mx-bridge
   python3 --version
   codex --version
   ```

   The ZIP works too; extract it and enter its `codex-mx-bridge` directory.
   Use Python 3.10 or newer. macOS's bundled Python, if any, may be older;
   use an independently installed current Python in that case.

2. Preview the hook configuration, then merge it into your Codex home:

   ```sh
   python3 bridge.py install-hooks
   python3 bridge.py install-hooks --apply
   ```

   The installer preserves existing entries, including Herdr's entries, and
   writes a timestamped backup before replacing an existing `hooks.json`.
   It does not edit `config.toml`. Set `CODEX_HOME` before running it if you use
   a custom Codex home, or use `--codex-home /absolute/codex/home`.

3. Restart Codex. Open `/hooks`, review the bridge command definitions, and
   trust them. **This review is required by Codex for non-managed hooks.** New
   or modified definitions are skipped until reviewed. If `/hooks` or these
   events are unavailable, update the CLI before relying on this bridge.
   No minimum release is claimed without evidence; see [interfaces](docs/INTERFACES.md).

   Hooks are currently on by default. If your existing config disables them,
   merge `hooks = true` into its existing `[features]` table. Managed policy may
   prohibit user hooks; this installer does not bypass that policy.

4. Install Logi Options+ and connect the MX Creative Console. Install the supplied
   `CodexMx_0_1_0.lplug4` by double-clicking it, or build from source below.
   Restart **Logi Plugin Service** in Options+ settings if the actions do not
   appear. The package format and installation path are documented in
   [Logitech's SDK guide](https://logitech.github.io/actions-sdk-docs/csharp/plugin-features/install-and-uninstall/).

5. In Options+, map **Codex MX Bridge → Agents → Agent slot 1** through
   **Agent slot 9** to the nine LCD keys. Map **Agent pages** to the dial to
   browse all rows. Alternatively map **Next agent page** to an available
   button. Assign these in the iTerm2 profile or a profile you keep selected.
   The plugin provides actions; it does not overwrite your device profile.

6. Start Codex in iTerm2, submit a prompt, and inspect status:

   ```sh
   codex
   # In a separate terminal:
   python3 /absolute/path/codex-mx-bridge/bridge.py status
   ```

   For process heartbeat and exit detection, launch it through the optional
   wrapper. All CLI arguments after `--` pass through unchanged:

   ```sh
   python3 /absolute/path/codex-mx-bridge/bridge.py run --label api -- codex
   python3 /absolute/path/codex-mx-bridge/bridge.py run -- codex resume
   ```

   The wrapper inherits the terminal rather than capturing Codex's screen.
   Its ten-second heartbeat proves process liveness only. It does not prove
   model progress. Without it, an unrefreshed row becomes `STALE` after 15
   minutes; a long reasoning interval can therefore be stale while still running.
   With it, a missing heartbeat becomes stale after 45 seconds.

7. On a direct local iTerm session, pressing its status key selects the original
   window/tab/pane. macOS may request Automation access for Logi Plugin Service
   to control iTerm2. Permit that only if you want this focus feature. Status
   updates work independently. A reused/closed terminal cannot be reconstructed.
   Focus results appear in `~/.local/state/codex-mx-bridge/focus-status.txt`.

## Status meanings

These are observations, not a complete agent state machine. In particular,
`APPROVAL?` means a permission hook ran; another hook might resolve it immediately.

| Display | Last observation |
| --- | --- |
| `READY` | Session started or resumed |
| `WORKING` | Prompt submitted, tool returned, or compaction finished |
| `TOOL` | A supported local tool is about to run |
| `APPROVAL?` | Codex was about to request permission |
| `COMPACT` | Compaction started |
| `TURN STOP` | Main turn reached the Stop hook; another hook may continue it |
| `STOPPED` | Subagent reached SubagentStop; continuation is still possible |
| `INTERRUPTED` | Main turn interrupted |
| `CLOSED` | SessionEnd observed, or optional wrapper child exited with code 0 |
| `EXIT ERROR` | Wrapper child exited nonzero; no claim about individual tool failures |
| `NO HOOKS` | Launcher is alive but no hook has reached this run yet |
| `STALE` | Liveness/event age exceeded its threshold |
| `OFFLINE` | SSH poll failed, or collector has been silent for 15 seconds |
| `NO DATA` / `READ ERROR` | Hook data missing or unreadable; inspect the bridge directory |

Each tile shows a host label and project label. Child rows have a `>` prefix.
Rows retain registration order; active rows do not jump between keys on every
event. Completed rows remain until cleared. Each host retains at most 256 local
rows; eviction increments a visible `PRUNED` indicator. Page with the dial.

```sh
# Remove closed/stopped/expired local history; active recent rows remain.
python3 bridge.py clear
# Remove only the named remote cache.
python3 bridge.py clear --remote linux-desktop
```

## Herdr and remote Linux

**Herdr can coexist with this bridge.** Its Codex integration and this installer
both use `hooks.json`; merge the entries rather than replacing that file. Install
the bridge on every machine that actually runs Codex, including Linux. Merely
installing it on the Mac does not instrument a remote Codex process.

For commands, connection recovery, and limitations, follow
[SSH and Herdr setup](docs/REMOTE-AND-HERDR.md). The separate assessment examines
whether Herdr's own event/status API would justify an additional adapter or plugin;
that integration is not required for this version's hook transport.

## Build, tests, and simulated data

Install the .NET 8 SDK to build or run C# tests. The plugin references the real
Logitech API supplied by Options+. It never silently substitutes a fake SDK.

```sh
python3 scripts/test_all.py
python3 tests/codex_hook_smoke.py
python3 scripts/build_plugin.py --link
```

The real-CLI test uses a loopback fixture with a temporary `CODEX_HOME`, no user
credentials, and no external model. Its trust-bypass flag applies only to the
test's temporary generated hook scripts; normal setup uses `/hooks` review.

If the API DLL is installed elsewhere:

```sh
python3 scripts/build_plugin.py --sdk '/actual/path/PluginApi.dll' --link
```

Package and verify with the tested .NET 8-compatible tool version:

```sh
dotnet tool install --global LogiPluginTool --version 6.1.4.22672
# Include ~/.dotnet/tools in PATH if required by your .NET installation.
python3 scripts/build_plugin.py --pack
```

The latest tool package failed installation under this test machine's .NET 8 SDK;
version `6.1.4.22672` installed, supplied the real SDK assembly, and successfully
packed/verified the plugin. A newer compatible .NET SDK may support the latest tool.
The host still supplies `PluginApi.dll` at runtime; it is not redistributed here.

Without hardware, generate isolated synthetic events:

```sh
python3 bridge.py --state-dir /tmp/codex-mx-demo demo
python3 bridge.py --state-dir /tmp/codex-mx-demo status
```

The plugin uses the default directory unless **Logi Plugin Service's own**
environment contains `MX_CODEX_STATE_DIR`. Setting it only in a terminal does
not change the environment of an already-running GUI service. Keep the default
for normal installation; the demo is primarily for tests and inspection.

## macOS and hardware acceptance checks

These require your Mac, current Options+, iTerm2, and console. They have not been
claimed as passed on the Windows build machine.

1. Trust the hooks, start a fresh Codex session, and confirm a non-demo row appears.
2. Submit a prompt; confirm the keys refresh without pressing them.
3. Trigger a normal approval request under your existing approval settings; the
   `APPROVAL?` state may be brief. Do not change security settings just for this check.
4. End and interrupt separate turns; compare `TURN STOP` and `INTERRUPTED`.
5. Run two direct iTerm panes with distinct labels; press each key and confirm focus.
6. Run an agent inside Herdr; confirm Herdr's existing integration still works and
   the bridge receives hooks. Button press must not select an obsolete iTerm pane.
7. Configure SSH collection; disconnect it and confirm `OFFLINE`, then reconnect
   and confirm recovery. The Linux agent should continue while the Mac is detached.
8. Create more than nine rows and check dial paging and compact tile legibility.

## Uninstall and troubleshooting

```sh
# Preview, then remove only bridge hook handlers. Existing Herdr hooks survive.
python3 bridge.py install-hooks --remove
python3 bridge.py install-hooks --remove --apply
```

Restart Codex after removal. Stop SSH collectors, remove the plugin through
Options+ or LogiPluginTool, and remove `CodexMxPlugin.link` from the macOS Plugin
Service Plugins directory if you used `--link`. The source and state directories
can then be deleted manually if you no longer need them. No LaunchAgent is
installed automatically and no system settings are changed by the bridge.

* Missing data: check the effective `CODEX_HOME`, `/hooks` trust, feature policy,
  and absolute Python/project paths. Restart existing Codex sessions after setup.
* Hooks fail: a generic `hook-error.txt` records failure without prompt content.
  Corrupt `state.json` is preserved rather than overwritten. Stop writers,
  rename the corrupt file for diagnosis, then restart. The advisory handler
  exits 0 and emits `{}` even on bridge errors.
* Plugin missing: restart Logi Plugin Service; check the installed SDK path,
  package validation, and Options+ action picker. Do not install both a `.link`
  and packaged copy of the same plugin simultaneously.
* Focus missing: check `focus-status.txt` and macOS Automation settings. Herdr,
  remote machines, SSH sessions, and terminal sessions without a usable iTerm ID
  are not eligible for automatic focus in this version.
* Remote data missing: run the `collect-ssh --once` command first and inspect the
  stored remote error. SSH aliases and host keys must already work noninteractively.

See [the interface audit](docs/INTERFACES.md) before extending the protocol.
