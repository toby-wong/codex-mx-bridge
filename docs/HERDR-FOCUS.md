# Focus a local Herdr chat from an MX button

Pressing a local Herdr agent tile selects the pane currently reporting that
Codex chat, then brings its configured iTerm2 window, tab, and pane forward.
This requires the updated bridge hooks and plugin, Herdr's Codex integration,
and one explicit binding for each local Herdr server.

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
socket identity. If an older Codex process still runs the old hook command,
reload/trust the updated hooks or restart that Codex session. Herdr must also
have received its native Codex session ID through its own integration.

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

1. The tile is local and carries a Codex session ID and local Herdr socket.
2. That exact socket has an explicit iTerm2 binding.
3. `agent.list` identifies exactly one current Codex agent whose
   `agent_session.kind` is `id` and whose value matches the chat.
4. The configured iTerm2 pane still exists and macOS permits AppleScript access.
5. `agent.get` still reports the same chat, pane, and stable terminal identity.
6. `agent.focus` selects it and returns the expected identity; the iTerm2
   window/tab/pane is then selected and activated.

The whole action has an eight-second deadline. Simultaneous button presses
are ignored while a focus action is running. Errors appear in
`~/.local/state/codex-mx-bridge/focus-status.txt`; the page action shows
`NO FOCUS`. Missing bindings, ambiguous identities, disconnected servers,
reused panes, or missing Mac panes fail visibly.

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

The new focus path still needs an on-device press with the intended Herdr
client attached. It has not been used to change the user's active pane during
development.
