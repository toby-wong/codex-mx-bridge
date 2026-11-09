# Settings app

Run the installed launcher to open the bridge settings in your browser:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx settings
```

The app uses the existing Python runtime. There is no frontend build, npm
dependency, or account to configure. Display settings continue to hot reload;
editing them does not require a plugin rebuild or restart.

On macOS, install a Finder launcher in `~/Applications`:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx settings --install-app
```

Then open **Codex MX Bridge.app** from Finder or Spotlight. It starts or reuses
the local server and opens a browser tab. The normal Mac installer also writes
a launcher inside its install prefix, next to `installation.json`. Custom
prefixes use the command path printed by the installer.

For an older installation, add just the app from this checkout using the
bridge's existing runtime:

```sh
~/.local/share/codex-mx-bridge/venv-3.15/bin/python bridge.py settings --install-app
```

This stages an immutable source release, installs the Finder app, and writes
`~/.local/share/codex-mx-bridge/bin/codex-mx-settings`. It preserves the existing
agent hooks, plugin, and main launcher. The separate app's release is recorded
in `settings-app.json` under the install prefix. Rerun this command to update
that app after pulling changes. Its command accepts `--stop` and `--no-open`
just like `codex-mx settings`.

## Controls

- **Display:** pet or text mode, default pet, animation, requested 1–8 fps,
  each caption switch, and all four chat views. The nine-button browser preview
  shows the draft with either your current chats or clearly labeled examples.
- **Pet library:** preview imported revisions, select a default, or import
  a PNG/WebP atlas or `.codex-pet.zip` from a file or remote URL. Codex Pets
  page links resolve to the downloadable package automatically. An optional
  layout JSON supports other atlas geometries. Importing adds a pack;
  selecting it takes effect on save.
- **Assignments:** add, edit, reorder, or remove rules for Codex, Claude, Kiro,
  Pi, local/remote location, remote source, or a stable chat key. All selectors
  must match; the last matching rule wins.
- **Chats & names:** give a chat or child agent a display name and individual
  pet. The picker uses stable keys, so choices follow chats as tabs and buttons
  reorder. Search also accepts an exact key or host.
- **Bridge & focus:** inspect source and plugin diagnostics, edit explicit
  Herdr-to-iTerm bindings, and import/export display settings. Remote bindings
  use existing SSH trust; the app does not create connections or execute agents.

Click **Save changes** for display settings or **Save bindings** for terminal
targets. Importing display settings first validates them and puts them into
the editor; save explicitly to apply them. Export includes the current draft,
including any unsaved display changes. Exported settings do not include artwork.

In **Pet library → Add a pet**, choose **Remote URL** and paste a link such as
`https://codex-pets.net/#/pets/banana-cat`, or a direct HTTPS ZIP, PNG, or WebP
URL. The app suggests a library name, which you can edit. Click **Import pet**
to download and add it, then use the default picker or an assignment to select
it. Importing alone leaves current selections unchanged.

You can also download pets yourself from [Codex Pets](https://codex-pets.net/#/)
and choose **File on this computer**. Both methods accept up to 20 MiB.
Community artwork stays on your computer and is not bundled with this project.
Pet import uses the optional Pillow extra; install it once with
`bash install.sh --with-pets`. Already imported pets can be previewed without
Pillow.

## Existing files and edits

The app uses `~/.config/codex-mx-bridge/display.json` and the existing
`~/.local/state/codex-mx-bridge/herdr-focus.json`. A custom `--state-dir`
keeps both documents inside that directory. Existing legacy display settings
are read and migrated on save using the same path rules as the CLI.

Saves use the bridge's validators, a private backup beside the changed file,
and an atomic replacement. Unknown configuration fields are retained.
Backups are named `display.json.settings-backup-<timestamp>` or
`herdr-focus.json.settings-backup-<timestamp>`.

The app polls for file changes every two seconds while visible. A clean editor
refreshes automatically. If a file changes while you have unsaved edits, the
app keeps the draft and blocks saving until you reload the file. Two app tabs
cannot silently overwrite each other's settings. As with any file editor,
an external program that writes in the instant between the final revision
check and atomic replacement cannot participate in this concurrency check.

Plugin diagnostics show the last recorded config/render/focus messages, not a
hardware connection heartbeat. The browser preview approximates the console;
the Logitech SDK retains responsibility for font fitting and final rendering.

## Local server

The server binds only to `127.0.0.1` on an available port. A random private
launch token authorizes settings, metadata, uploads, and image requests.
The browser removes the token from the address bar after opening. Foreign
hosts/origins are rejected. Fonts and scripts stay local. Pasting a remote
pet URL and clicking **Import pet** downloads its artwork through the local
server. Downloads use public HTTPS destinations, verified TLS, bounded sizes
and redirects, and a shared deadline. Each redirect is checked and connections
use the validated IP address. Local/private addresses, URL credentials, and
HTTP downgrades are rejected; browser cookies and bridge tokens are never sent
to download hosts. The community catalog opens separately when clicked.

Closing the browser leaves the small settings server available for the next
launch. **Quit settings app**, or the command below, stops only that server:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx settings --stop
```

Agent hooks, SSH collectors, the plugin, and their state keep running. If a
browser tab loses its connection after an update, open the app again. A launch
reuses the running server only when it matches the current source release.
The private runtime record and server log live in the bridge state directory
as `settings-server.json` and `settings-server.log`.

For development, use an isolated directory and print the private launch URL:

```sh
python3.15 bridge.py --state-dir /tmp/mx-settings-demo demo
python3.15 bridge.py --state-dir /tmp/mx-settings-demo settings --no-open
python3.15 bridge.py --state-dir /tmp/mx-settings-demo settings --stop
```

`--port NUMBER` selects a loopback port. `--foreground` runs the server in the
terminal until interrupted. There is no option to expose it on a network
interface.

## Validation

The normal `scripts/test_all.py` runner includes the settings API and model
tests. They cover persistence, backups, conflict detection, local/remote rule
selection, ZIP/download limits, URL validation, redirects, authentication, path
containment, and launcher reuse.

The optional browser acceptance suite needs Playwright with Chromium and the
Python pets extra:

```sh
MX_TEST_PYTHON=/absolute/path/to/python3.15 \
MX_PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs \
node --test tests/settings_browser.test.mjs
```

Omit `MX_PLAYWRIGHT_MODULE` when `playwright` is already resolvable by Node.
The suite uses generated geometry fixtures and an isolated state directory.
It tests saving, paging, captions, FPS, rule reordering, chat overrides,
external edits, file/URL import, config import/export, Herdr bindings, and narrow
layouts. Browser URL success uses a fixture transfer; Python tests cover the
downloader separately. Screenshots go to ignored `test-results/settings-browser/`.
