# Local settings app

## Intended result

Open **Codex MX Bridge** on the Mac, or run `codex-mx settings`, to edit the
bridge in a small browser app. Save to the existing display configuration and
let the plugin hot reload it. Keep the user's current selections, pet rules,
sessions, hook configuration, and locally installed artwork.

## Implementation

1. Add a loopback-only Python settings server, launched on demand by the CLI.
   Reuse the installed runtime, configuration validators, and pet importer.
   Serve bundled HTML, CSS, and JavaScript without a frontend build or remote
   dependencies. Give the macOS installer an application launcher.
2. Provide display mode, motion, 1–8 fps, caption switches, all four chat views,
   a default pet picker, and an approximate animated button preview.
3. Show the installed pet library. Import a user-selected PNG/WebP atlas or
   `.codex-pet.zip` package, or paste a Codex Pets page/direct HTTPS file URL,
   with an optional custom layout. Link to the community catalog; keep
   downloaded and imported artwork out of Git.
4. Edit ordered pet rules by agent client, local/remote location, host, or
   stable chat key. Support chat name overrides and selecting live chats
   without copying IDs. Show which rule supplies each chat's pet.
5. Show collector and plugin diagnostics. Allow editing explicit local/remote
   Herdr terminal bindings using the existing validators. This app does not
   run agent commands, install hooks, or change SSH trust.
6. Save validated settings atomically with a backup and a revision check.
   Poll external changes without losing unsaved UI edits; provide explicit
   reload when a conflict occurs. Support settings download/upload.
7. Bind only to `127.0.0.1`, use a random per-launch token, reject foreign
   hosts/origins, and keep private files behind authenticated endpoints.
   Bound uploads, downloads, redirects, and ZIP expansion. Restrict download
   destinations to public HTTPS hosts; serve only imported image frames.

## Validation

- Python tests: settings persistence, validation, backups, concurrent edits,
  archive handling, public URL downloads, authenticated HTTP, path containment,
  and app launch.
- JavaScript tests: exact rule precedence, stable chat identities, all four
  chat views, labels, and draft preservation.
- Browser checks: display save, pet import/selection, local/remote rules,
  renames, file conflicts, keyboard use, and narrow-screen layout.
- Run the existing test suite. Install/open the app locally and verify one
  reversible display change reaches the running plugin, then restore the
  user's original setting. Browser previews do not establish hardware output.
