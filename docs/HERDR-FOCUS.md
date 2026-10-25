# Focus a Herdr chat from an MX button

Pressing a Herdr agent tile selects the pane currently reporting that
Codex chat, then brings its configured iTerm2 window, tab, and pane forward.
This requires the updated plugin, Herdr's Codex integration, and one explicit
binding for each Herdr server/session. Local bindings use a Unix socket;
remote bindings use ordinary OpenSSH and the remote Herdr CLI. Both paths
currently match Codex native session IDs.

## Bind a local terminal

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

## Bind a remote terminal (`herdr --remote`)

The collector's source alias and the SSH target are separate values. For
example, if collection uses `--host workbox --alias linux-desktop`, and your
Mac terminal displays `herdr --remote workbox`, bind it with:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx herdr-focus bind \
  --remote linux-desktop --ssh-target workbox \
  --herdr-path /home/your-linux-user/.local/bin/herdr \
  --iterm-id 'OUTER_ITERM_SESSION_UUID'
```

Use the remote executable path reported by `ssh workbox 'command -v herdr'`.
If it is already on the remote noninteractive PATH, omit `--herdr-path`.
`--ssh-target` defaults to the source alias. Ports, identity files and proxy
jumps belong in your existing OpenSSH config. Authentication and host-key
verification must work noninteractively; Herdr's private SSH connection is
not reused. Each button press creates its own short-lived SSH connection;
lookup, identity verification and focus share it, avoiding three separate
authentication handshakes. The bridge closes it after the action.

Run the command in the outer local iTerm2 shell before attaching if you want
to omit `--iterm-id` and capture that shell's UUID automatically. The same
binding also works for an iTerm pane running `ssh workbox` followed by `herdr`.
Keep the mapped terminal attached to the specified server/session.

For `herdr --remote workbox --session work`, add `--remote-session work` to
the binding command. Omit it for the default Herdr session. Multiple named
sessions can be bound under one source; every bound session must be reachable,
and exactly one must report the selected native chat ID.

The private file `~/.local/state/codex-mx-bridge/herdr-focus.json` (or the
configured bridge state directory) contains both kinds of binding:

```json
{
  "schema_version": 1,
  "bindings": [],
  "remote_bindings": [
    {
      "source": "linux-desktop",
      "ssh_target": "workbox",
      "herdr_path": "/home/your-linux-user/.local/bin/herdr",
      "remote_session": "",
      "iterm_id": "12345678-1234-1234-1234-123456789abc"
    }
  ]
}
```

Replace the example values with your actual paths and UUID. There are at most
16 local and 16 remote bindings. Both lists are read on every button press;
changing a binding needs no plugin rebuild or restart. Rebinding the same
source/session replaces only that entry. To remove it:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx herdr-focus remove \
  --remote linux-desktop
# For a named session, also pass --remote-session work.
```

## What a press checks

1. The tile is marked as Herdr and carries a Codex session ID.
2. A local row's socket has an explicit iTerm2 binding; a socket-less local
   row searches only bound local servers. A remote row's full source alias
   selects only explicitly bound SSH targets/sessions. Its display caption,
   socket path and terminal metadata cannot choose a local server or Mac pane.
3. `agent.list` identifies exactly one current Codex agent whose
   `agent_session.kind` is `id` and whose value matches the chat. For a
   socket-less local row or remote source with multiple sessions, every
   applicable bound server must be reachable and exactly one matching identity
   must exist across them all.
4. The configured iTerm2 pane still exists and macOS permits AppleScript access.
5. `agent.get` still reports the same chat, pane, and stable terminal identity.
6. `agent.focus` selects it and returns the expected identity; the iTerm2
   window/tab/pane is then selected and activated.

Focus requests have an eight-second deadline; closing the action's SSH
connection has a separate one-second cleanup limit. Simultaneous button presses
are ignored while a focus action is running. Errors appear in
`~/.local/state/codex-mx-bridge/focus-status.txt`, together with the selected
row key, client and native session ID; the page action shows `NO FOCUS`.
Missing bindings, ambiguous identities, disconnected servers, reused panes,
or missing Mac panes fail visibly. A project name is never used to guess a
chat, and a row with an explicit socket never falls back to another server.
Remote failures never fall back to a local socket or another source. SSH focus
calls only `herdr agent list`, `get`, and `focus`; it disables forwarding,
quotes remote arguments, caps stdout at 1 MiB and stderr at 16 KiB, and kills
the SSH process if the action times out.

Herdr's public focus operation is session-wide and marks completion as seen.
It can change the selected pane in other clients attached to the same server.
There is no public atomic "focus only if this chat still occupies the pane"
operation; the bridge checks identity immediately before the focus request
and checks the returned identity afterward.

The binding identifies the intended Mac terminal, not a Herdr client ID.
Keep that terminal attached to the specified Herdr session. The bridge
does not start Herdr, attach detached clients, switch a client between machines,
restore closed chats, or type into a terminal. Plain SSH rows without Herdr
remain ineligible. Remote exports still strip all socket and Mac terminal
targets; only the locally maintained binding authorizes a remote focus action.

## Validation

The remote path was checked against installed Herdr CLI/server 0.9.5,
protocol 22, and upstream v0.9.5's public session-wide focus implementation.
Portable tests cover local/remote identity checks, terminal preflight, binding
management, source isolation, shell argument quoting, SSH failures, response
limits, cancellation, and bounded local socket transport.

To inspect current local and remote Herdr row mappings without selecting a pane, run
from the checkout with .NET 8 available:

```sh
dotnet run --project tests/ViewModelTests -- --probe-focus-map \
  "$HOME/.local/state/codex-mx-bridge/state.json" \
  "$HOME/.local/state/codex-mx-bridge/herdr-focus.json"
```

It runs the portable checks, then reports the unique live target or reason
each Herdr row is unavailable. Retained history can appear on a button without
having a live pane to focus.

Live validation on 25 October 2026 confirmed switching remote workspaces
through the installed plugin and selecting the corresponding Mac iTerm pane.
The user also confirmed a physical MX button selected the correct remote chat.
With the remote Herdr tab moved from position 1 to 9 and its outer iTerm tab
moved from position 1 to 3, the same native chat, terminal identity and Mac UUID
were still selected. The test restored both tab orders and the original focus.
Bindings follow identities, so tab order does not require rebinding. Observed
remote focus took 6–7 seconds including SSH setup.
