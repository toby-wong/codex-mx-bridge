# Pages and recent chats

The bridge can show more than nine chats. Each page contains nine rows.
In Logi Options+, assign **Codex MX Bridge → Agents → Agent pages** to the
dial to browse them. Alternatively, assign **Next agent page** to a spare
control. Keep **Agent slot 1** through **Agent slot 9** on the LCD buttons:
the same actions display each successive page.

The page indicator reports the current page and total, such as `2/3`.
The normal view preserves local registration order, then remote sources.

## Select a view

Edit `~/.config/codex-mx-bridge/display.json` and set `chat_view`:

| Value | Buttons show |
| --- | --- |
| `paged` | All rows across pages of nine, in the existing stable order; the default |
| `recent` | The nine rows with the latest activity, including finished chats |
| `recent_open` | The nine rows with the latest activity, excluding finished chats |
| `newest` | The nine most recently created rows, using their recorded creation time |

For example, keep the other fields and add:

```json
"chat_view": "recent_open"
```

Or use the installed launcher, which preserves all other settings:

```sh
~/.local/share/codex-mx-bridge/bin/codex-mx display --chat-view recent
~/.local/share/codex-mx-bridge/bin/codex-mx display --chat-view recent_open
~/.local/share/codex-mx-bridge/bin/codex-mx display --chat-view newest
~/.local/share/codex-mx-bridge/bin/codex-mx display --chat-view paged
```

These settings reload on the existing 500 ms polling cycle once this plugin
version is installed. The three recent views have one page. Switching back
to `paged` exposes the retained history; filtering never deletes state.
All views work with text and pets and combine local and remote rows.
The plugin also reads the old state-folder config when the new file is absent.
With a custom `--state-dir` or `MX_CODEX_STATE_DIR`, settings remain in that
directory so isolated configurations stay separate.

## What the ordering means

Activity means the latest accepted hook event or wrapper exit. Launcher
heartbeats and SSH polls do not make an idle chat appear recently active.
The SSH transport converts ages into the Mac's clock before sorting.

Finished means `CLOSED`, `EXIT ERROR`, or a child agent's `STOPPED`.
`TURN STOP` and `TURN ERROR` leave a conversation open, so they remain in
`recent_open`. `STALE` and `OFFLINE` do not prove that a chat has closed.
An offline row's recorded closed status is still respected by the filter.
Child agents are rows and can occupy a button, as in the paged view.

New bridge rows retain `created_at` from their first observed event.
Activity, resume, compaction, and heartbeat updates do not reset it. This
is the time the bridge first observed the row; if its initial hook was
missed, it is not a recovered native chat creation time.

Older rows and older remote exporters lack this field. In `newest`, rows
with known creation times come first. Unknown rows follow, grouped by source
and ordered by newest registration within that source. Their true relative
start time across machines cannot be recovered from existing state.
Use updated hooks and restart older collectors to record/transport creation
times for new rows; existing history is not assigned invented timestamps.

Recent views can move chats between positions when activity changes. A press
uses the chat identity from that button's last completed image render, rather
than a newly sorted position that has not yet rendered. Names and overrides
also follow row identity. Remote focus remains unsupported.

Diagnostics such as an empty offline source or a history-pruning notice fill
unused positions; they do not evict one of nine selected chat rows.
The paged view retains the complete diagnostic list.
