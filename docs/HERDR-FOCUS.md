# Focus a local Herdr chat from an MX button

Pressing a local Herdr agent tile selects the pane currently reporting that
Codex chat, then brings its configured iTerm2 window, tab, and pane forward.
This requires the updated plugin, Herdr's Codex integration, and one explicit
binding for each local Herdr server. Updated bridge hooks also record the
specific server socket in each row.

## Bind the terminal

From the source checkout, in the **outer local iTerm2 shell** that will display
Herdr, upgrade the installed bridge and register the terminal in one command:

```sh
bash update.sh --bind-herdr "$HOME/.config/herdr/herdr.sock"
```

The updater rebuilds/reloads the plugin and preserves your pet settings and
button assignments. Review the changed Codex hooks in `/hooks` afterward.
`--dry-run` previews the operation; `--no-restart` defers the plugin reload.

If the updated hooks and plugin are already installed, register just the
socket for that Herdr session:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx herdr-focus bind \
  --socket "$HOME/.config/herdr/herdr.sock"
```

That path is for the default Herdr session. For another session, use its socket
from `herdr session list` or `HERDR_SOCKET_PATH` inside that Herdr session.
The binding command records the outer shell's `ITERM_SESSION_ID`. Then attach
that iTerm2 pane to the corresponding Herdr session normally.

If Herdr is already running in the desired window, an explicit outer iTerm2 ID
can be provided from another shell:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx herdr-focus bind \
  --socket "$HOME/.config/herdr/herdr.sock" \
  --iterm-id 'OUTER_ITERM_SESSION_UUID'
```

Replace the placeholder with the actual outer iTerm2 session UUID (the full
`w…:UUID` value is also accepted). Automatic capture from inside Herdr or SSH
is rejected because those processes may inherit an obsolete terminal ID.
The command writes only the bridge's private `herdr-focus.json`; it does not
start, attach, focus, or reconfigure Herdr.

After the next accepted bridge hook, existing Herdr rows gain their local
socket identity. An older Codex process can retain the old hook command;
socket-less rows can still focus when exactly one bound server reports that
native chat ID. Reload/trust the updated hooks or restart that Codex session
to populate its socket. Herdr must have received its native Codex session ID
through its own integration.

Inspect or remove bindings:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx herdr-focus list
~/.local/share/codex-mx-bridge/bin/codex-mx herdr-focus remove \
  --socket "$HOME/.config/herdr/herdr.sock"
```

Bindings are read on each press. Rebinding the same socket replaces its
terminal mapping and preserves other sessions. Rebind after moving the Herdr
client to another iTerm2 pane; a binding does not track client moves or changes
of the machine displayed in a client.

## What a press checks

1. The tile is local, marked as Herdr, and carries a Codex session ID.
2. If the row records a socket, that exact socket has an explicit iTerm2
   binding. For an older row without a socket, inspect only explicitly bound
   local servers.
3. `agent.list` identifies exactly one current Codex agent whose
   `agent_session.kind` is `id` and whose value matches the chat. For a
   socket-less row, every bound server must be reachable and exactly one
   matching identity must exist across them all.
4. The configured iTerm2 pane still exists and macOS permits AppleScript access.
5. `agent.get` still reports the same chat, pane, and stable terminal identity.
6. `agent.focus` selects it and returns the expected identity; the iTerm2
   window/tab/pane is then selected and activated.

The whole action has an eight-second deadline. Simultaneous button presses
are ignored while a focus action is running. Errors appear in
`~/.local/state/codex-mx-bridge/focus-status.txt`, together with the selected
row key, client and native session ID; the page action shows `NO FOCUS`.
Missing bindings, ambiguous identities, disconnected servers, reused panes,
or missing Mac panes fail visibly. A project name is never used to guess a
chat, and a row with an explicit socket never falls back to another server.

Herdr's public focus operation is session-wide and marks completion as seen.
It can change the selected pane in other clients attached to the same server.
There is no public atomic "focus only if this chat still occupies the pane"
operation; the bridge checks identity immediately before the focus request
and checks the returned identity afterward.

The binding identifies the intended Mac terminal, not a Herdr client ID.
Keep that terminal attached to the specified local Herdr session. The bridge
does not start Herdr, attach detached clients, switch a client between machines,
restore closed chats, or type into a terminal. Remote SSH rows remain
ineligible for button focus, and remote exports strip Herdr socket paths.

## Validation

The implementation was checked against installed Herdr CLI 0.9.5 schemas and
read-only responses from the user's running server, which reported version
0.9.3/protocol 22. The public focus response was verified against upstream
v0.9.3 source. Portable tests cover the identity checks, terminal preflight,
binding management, source isolation, and bounded socket transport.

To inspect current local Herdr row mappings without selecting a pane, run
from the checkout with .NET 8 available:

```sh
dotnet run --project tests/ViewModelTests -- --probe-focus-map \
  "$HOME/.local/state/codex-mx-bridge/state.json" \
  "$HOME/.local/state/codex-mx-bridge/herdr-focus.json"
```

It runs the portable checks, then reports the unique live target or reason
each Herdr row is unavailable. On 25 October, this resolved the legacy row at
slot 3 to `wP:p4`; slot 4 had no matching native identity in the live server.
Retained history can therefore appear on a button without having a current
focus target.

The new focus path still needs an on-device press with the intended Herdr
client attached. It has not been used to change the user's active pane during
development.
