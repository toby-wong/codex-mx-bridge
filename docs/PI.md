# Pi and Pi Herdr Agents

Pi 1.5.0 or later can report session activity to the bridge. Parents and
`pi-herdr-agents` children each get a row, locally or through the SSH collector.
The integration was developed against Pi 1.5.0, Pi Herdr Agents 3.7.2, and
Herdr 0.9.5.

## Install

Update an existing bridge from this checkout, then install the Pi extension:

```bash
bash update.sh
~/.local/share/codex-mx-bridge/bin/codex-mx install-hooks --client pi --apply
```

For a new installation:

```bash
bash install.sh --client pi
```

Repeat `--client` to include Codex, Claude, or Kiro. On the cloud/Linux host,
use `--hooks-only`. Install the extension on each machine that runs Pi; the
Mac continues collecting cloud state through the existing SSH connection.
When upgrading an older cloud installation, update the collector's
`--remote-script` to the path printed by the installer.

The extension lives at `~/.pi/agent/extensions/codex-mx-bridge.ts`. It uses Pi's
automatic extension discovery and does not edit `settings.json`, model
configuration, role definitions, or Herdr's own Pi extension.

New Pi sessions load it automatically. Use `/reload` in an existing idle Pi
session to load a newly installed or updated extension. An active child also
needs its own reload or a later restart; reloading its parent does not reload
the child process.

The installer respects `PI_CODING_AGENT_DIR`. Select another agent directory
explicitly when needed:

```bash
~/.local/share/codex-mx-bridge/bin/codex-mx install-hooks \
  --client pi --pi-agent-dir /absolute/project/.pi/agent --apply
```

Pi Herdr Agents can select a project's `.pi/agent` directory, including inside
a worktree. Install there when that directory replaces the usual user agent
directory. The installer records selected targets so `update.sh` retains them.

## Status, children, and names

| Button status | Observed Pi state |
| --- | --- |
| `READY` | An idle session has attached |
| `WORKING` | An agent run is active |
| `TOOL` | At least one tool is outstanding |
| `WAITING` | An extension UI prompt is waiting for input |
| `COMPACT` | Compaction is in progress |
| `TURN STOP` | The run has settled with no automatic continuation pending |
| `TURN ERROR` | The final observed outcome was an error |
| `INTERRUPTED` | The run settled after an abort |
| `CLOSED` | The session attachment shut down |

Pi's `agent_end` can be followed by retries, compaction, or queued work. The
bridge uses `agent_settled` for final idle status. A failed tool alone does not
mark the whole turn as failed.

Children use their own native Pi session IDs. Launch IDs identify the current
delegation but are not the button key, so resuming a child with a new launch ID
updates the same row. Persistent specialists remain visible between tasks.

Names come from Pi's session-name API, falling back to the child launch name
or project directory. `use_chat_names: false` switches to that fallback without
reloading Pi. `show_name`, `show_client`, `show_location`, `show_status`, and
`name_overrides` apply normally.

Child rows record the role when the launcher supplies it. Parent associations
use structured launch/resume identity metadata or a reported parent path.
Standalone children can have no parent header; their buttons still work.
The current display is a flat list of sessions and children.

## Pets and recent chats

Use the existing hot-reloadable
`~/.config/codex-mx-bridge/display.json`. For example, merge these rules with
your existing configuration:

```json
{
  "pet_rules": [
    {"client": "pi", "location": "local", "pet": "clippit"},
    {"client": "pi", "location": "remote", "pet": "pingu"}
  ]
}
```

Existing location-only rules also apply to Pi. Client, remote host, and
individual chat-key selectors remain available. Role-wide pet rules are not
implemented. Install community artwork separately as described in
[pet setup](PET-DISPLAY.md); the bridge does not bundle those assets.

The paged and three recent-chat views include Pi parents and children. The
extension sends a heartbeat every 15 seconds with a 45-second presence lease.
Heartbeats, name refreshes, and reloads retain the last observed activity time,
so they do not move idle chats into the most recent nine.

Label, pet, FPS, and view changes reload from the display config without a Pi
reload or plugin reinstall.

## Button focus

Local Pi sessions in iTerm use the existing terminal-focus behavior. Pi inside
Herdr uses the same explicit terminal bindings as Codex:

```bash
codex-mx herdr-focus bind --socket /absolute/path/to/herdr.sock
codex-mx herdr-focus bind --remote clouddesk \
  --herdr-path /home/user/.local/bin/herdr
```

Run binding commands from the outer Mac iTerm pane, or provide `--iterm-id`.
See [Herdr focus setup](HERDR-FOCUS.md) for full instructions.

Herdr normally identifies Pi by its exact session-file path. The bridge keeps
that path separate from the native session ID and matches the client, identity,
pane, and terminal before focusing. It supports Herdr's explicit ID form too.
It does not derive identity from a filename or tab position. Remote paths are
matching data; the Mac never executes or opens them.

Headless JSON, print, and RPC sessions report status without claiming their
parent's terminal. A closed or ambiguous Herdr occupant reports a focus error.

## Diagnostics and removal

`codex-mx status` includes Pi rows and `hook_health.pi`. Reporting failures
write a generic `hook-pi-error.txt` in the state directory. The extension
exports selected metadata only; it does not forward prompts, tool arguments,
results, or provider credentials.

```bash
~/.local/share/codex-mx-bridge/bin/codex-mx install-hooks \
  --client pi --remove --apply
```

Use the same `--pi-agent-dir` if a custom target was installed. Removal backs
up the bridge-owned extension and updates the installation manifest. Existing
Pi processes retain loaded code until `/reload` or exit. Unowned, edited, or
symlinked extension files are preserved.

For native dispatch verification without model requests:

```bash
python3.15 tests/pi_hook_smoke.py
```

This starts isolated Pi parent/child sessions with a deterministic local
provider, verifies tools, settlement, resume, failure, and shutdown, and removes
the test directories. It does not establish physical-button verification.
