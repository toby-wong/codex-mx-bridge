# Animated pet buttons

Version 0.3.0 adds an optional local pet theme. Text remains the default. The
bridge chooses an animation from its observed status. Chat name, location,
client and status labels are independently configurable; the background colour
continues to reflect status. It does not mirror
the desktop app's selected pet or derive status from the app's animation.

## Install and select

Provide the original transparent PNG/WebP sprite sheet for your pet on the Mac.
From an updated checkout or extracted ZIP:

```sh
bash install.sh --with-pets --pet-sheet "$HOME/Downloads/my-pet.png" --pet-name buddy
```

This adds Pillow 13.0.0 to the isolated Python 3.15 environment, imports the
sheet and enables pet mode. Finish normal upgrade steps: review new definitions
in Codex `/hooks` and restart Logi Plugin Service. Keep existing button mappings.
No installable pet sprite pack is bundled in the project/download. The README
includes a rendered example using a locally imported pet.

Install only the importer with `bash install.sh --with-pets`. Then:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx pet import \
  --sheet "$HOME/Downloads/my-pet.png" --name buddy
~/.local/share/codex-mx-bridge/bin/codex-mx pet list
~/.local/share/codex-mx-bridge/bin/codex-mx display --mode pet --pet buddy --fps 4
~/.local/share/codex-mx-bridge/bin/codex-mx display --motion off
~/.local/share/codex-mx-bridge/bin/codex-mx display --mode text
```

Use the printed launcher path for a custom prefix. For several revisions of
one name, use a full `name/hex-revision` ID from `pet list`. Import does not
automatically select; `display` does. Settings reload within 500 ms without a
rebuild/restart once this plugin version is installed. `--motion off` can also
be passed to the installer. This preference is independent of OS/app reduced
motion settings, which the bridge does not read.

For a manual environment, install `.[pets]` or `Pillow==13.0.0`, then use
`python3.15 bridge.py`. Pillow is required only for import: hooks, SSH and
playback of imported frames do not need it. See [Pillow's Python support](https://pillow.readthedocs.io/en/stable/installation/python-support.html).

## Configure button labels

Edit `~/.config/codex-mx-bridge/display.json` to choose the captions on all
agent buttons. The plugin rereads it every 500 ms; after installing the version
with these controls, changing them needs no rebuild or service restart.
Existing files that omit the new fields show every label by default.

| Setting | Default | Effect |
| --- | --- | --- |
| `show_name` | `true` | Show the chat name, falling back to the existing project or agent label |
| `show_location` | `true` | Show `local` or `remote: <host alias>` |
| `show_client` | `true` | Show Codex, Claude or Kiro |
| `show_status` | `true` | Show the exact observed state, such as `TOOL` or `TURN STOP` |
| `use_chat_names` | `true` | Prefer a saved Codex chat name when available |
| `name_overrides` | `{}` | Supply display names keyed by stable row identity |
| `chat_view` | `"paged"` | Choose all pages or one of the three [recent chat views](CHAT-VIEWS.md) |

These switches also apply in text mode. In pet mode, hiding status text keeps
the same status animation and background colour. Set all four `show_…` switches
to `false` for just the pet; unused caption space becomes available to the
sprite. Bridge errors and empty slots still show diagnostic text.

The CLI preserves other settings when changing individual switches:

```sh
# Keep names and location, but communicate state through the pet.
~/.local/share/codex-mx-bridge/bin/codex-mx display --show-status off
# Show only the pet on populated agent buttons.
~/.local/share/codex-mx-bridge/bin/codex-mx display \
  --show-name off --show-location off --show-client off --show-status off
# Restore all captions.
~/.local/share/codex-mx-bridge/bin/codex-mx display \
  --show-name on --show-location on --show-client on --show-status on
```

Saved local Codex names come from the optional
`$CODEX_HOME/session_index.jsonl` name catalog, defaulting to
`~/.codex/session_index.jsonl`. Renames reload while the plugin is running.
Only `id` and `thread_name` are used; no conversation transcript or database
is opened. Missing names retain the project/agent label. Claude, Kiro, child
agents and remote rows retain their own existing labels unless overridden.

For any client, add entries to `name_overrides` using keys from `state.json`:
local entries use the `key` field in `rows`; remote entries use
`remote/<source alias>/<key from that source's rows>`, under `remotes`.
Use the whole key,
including an `@client/…` prefix when present. Keys follow the chat when page
positions change; they are not button numbers. For example:

```json
"name_overrides": {
  "local-codex-session-id": "Bridge work",
  "remote/clouddesk/remote-session-id": "Remote build"
}
```

Replace those illustrative keys with actual row keys. Overrides take priority
even when `use_chat_names` is `false`; that switch selects saved chat names or
project labels for rows without an override. Names are local display metadata,
are not written into agent state, and are not sent through SSH exports.

## Mapping and playback

| Status | Animation |
| --- | --- |
| READY | idle |
| WORKING, TOOL, COMPACT | running: focused work, not directional walking |
| APPROVAL? | waiting |
| TURN STOP, STOPPED | review; Stop does not prove success |
| EXIT ERROR, TURN ERROR | failed |
| STALE, OFFLINE, CLOSED, INTERRUPTED, NO HOOKS | still idle pose; exact label when enabled |
| Bridge errors / empty slots | text fallback |

The requested rate defaults to 4 fps and is bounded to 1–8. Only visible slots
with changed frames request redraw; decoded frames are cached. Hardware frame
rate/latency is not guaranteed. Reduce fps or disable motion if the keypad is
slow. Animation uses a monotonic local clock independently of hooks/SSH.

## Sheets and other app versions

Automatic layout: eight columns of 192 × 208 cells, v1 1536 × 1872 or v2
1536 × 2288. Standard rows/counts: idle 6; running-right 8; running-left 8;
waving 4; jumping 5; failed 8; waiting 6; running 6; review 6. The bridge uses
these nine rows and ignores v2's two additional look-direction rows.

This was checked against installed `work-pets` 0.1.6's `sprite-sheet-contract.md`.
The public [Pets documentation](https://learn.chatgpt.com/docs/pets) describes
local custom pets and the 1536 × 1872 web-upload layout. This is asset
compatibility, not an app export API. Complete cell bounds/alpha are preserved
to avoid per-frame recentering. All required standard frames must be nonempty.

A different built-in/app atlas must use an explicit layout, rather than guessed
rows. Use `pet import --sheet /path/atlas.png --name alternate --layout /path/layout.json`.
Example for a five-row atlas (replace geometry/rows with its actual values):

```json
{
  "frame_width": 192, "frame_height": 208, "columns": 8,
  "animations": {
    "idle": {"row": 0, "frames": 6},
    "running": {"row": 1, "frames": 6},
    "waiting": {"row": 2, "frames": 6},
    "review": {"row": 3, "frames": 6},
    "failed": {"row": 4, "frames": 8}
  }
}
```

Those five states are required. Limits: 512 × 512 cells; 32 columns; 128 frames;
4096 × 4096 image; 20 MiB encoded input. Only a single transparent PNG/WebP
atlas is accepted, not an animated image. Wrong geometry, blank required cells,
opaque backgrounds and unsafe names fail before publication. This is a
transport check, not official artistic/pet-upload validation.

## Files, recovery and limits

Packs: `~/.local/state/codex-mx-bridge/pets/<name>/<revision>/`, containing PNG
frames and `manifest.json`.
Settings: `~/.config/codex-mx-bridge/display.json`:

```json
{
  "schema_version": 1,
  "mode": "pet",
  "pet": "buddy/0123456789abcdef",
  "fps": 4,
  "animate": true,
  "show_name": true,
  "show_location": true,
  "show_client": true,
  "show_status": true,
  "use_chat_names": true,
  "name_overrides": {},
  "chat_view": "paged"
}
```

Keep your existing imported pet revision when editing labels. Settings are
limited to 64 KiB, with at most 64 name overrides, keys up to 700 characters and
names up to 80 characters. Control characters and blank keys/names are rejected.
Invalid settings, manifests,
missing frames or decoding errors fall back to text. Loading errors appear in
`display-status.txt`, which also records the active caption switches.
`render-status.txt` records a successful pet draw or a
rendering error, suppressing repeated identical results. Check both files when
pet mode is enabled but the buttons show text.
`display --mode text` also recovers from corrupt settings.
Treat packs as immutable; re-import changed artwork as a new revision and switch
away before removing a selected pack.

Older installations can keep using
`~/.local/state/codex-mx-bridge/display.json` until it is moved. The new config
location takes precedence when both exist, and the CLI writes changes to the
new location while preserving settings it read from the old file. Moving the
file does not require moving pet packs. The plugin rechecks the config location
on every polling cycle; `display-status.txt` records the path it is using.
An invalid new config produces an error rather than silently using old settings.

Custom state directories selected through `--state-dir` or
`MX_CODEX_STATE_DIR` keep their own `display.json` beside the state file.
This preserves isolated demos, tests and alternate installations.

Use the original custom sheet or a sheet you exported/have permission to use.
No supported API was verified for enumerating/exporting the desktop app's pets
or following its selection. This version does not extract app resources, read
private app settings/database, or use install deep links as an export API. If
only an installed built-in is available and its sheet cannot be obtained,
automatic reuse is not provided.

Imported packs remain on the Mac and never enter SSH exports. Linux needs no new
dependency/install for this display option; version-1 status export still works.
The Mac theme applies to local and remote rows. Tests use geometry fixtures, not
redistributed pet art. Physical motion, LCD legibility, host CPU load and the
user's particular sheet still require Mac/hardware checks.
