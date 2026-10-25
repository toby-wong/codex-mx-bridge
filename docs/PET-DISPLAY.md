# Animated pet buttons

Version 0.3.0 adds an optional local pet theme. Text remains the default. The
bridge chooses an animation from its observed status and keeps the host/project
header, exact status label and background colour visible. It does not mirror
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

## Mapping and playback

| Status | Animation |
| --- | --- |
| READY | idle |
| WORKING, TOOL, COMPACT | running: focused work, not directional walking |
| APPROVAL? | waiting |
| TURN STOP, STOPPED | review; Stop does not prove success |
| EXIT ERROR | failed |
| STALE, OFFLINE, CLOSED, INTERRUPTED, NO HOOKS | still idle pose plus exact label |
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
frames and `manifest.json`. Settings: `display.json` in the bridge state folder:

```json
{
  "schema_version": 1, "mode": "pet",
  "pet": "buddy/0123456789abcdef", "fps": 4, "animate": true
}
```

Use a real imported revision, not the example above. Invalid settings, manifests,
missing frames or decoding errors fall back to text. Loading errors appear in
`display-status.txt`. `render-status.txt` records a successful pet draw or a
rendering error, suppressing repeated identical results. Check both files when
pet mode is enabled but the buttons show text.
`display --mode text` also recovers from corrupt settings.
Treat packs as immutable; re-import changed artwork as a new revision and switch
away before removing a selected pack.

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
