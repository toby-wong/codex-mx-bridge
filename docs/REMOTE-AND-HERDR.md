# Herdr and Linux over SSH

## Herdr coexistence

Herdr's current Codex integration installs a `SessionStart` hook to report
session identity; Herdr obtains Codex status through screen detection. This
bridge independently observes Codex lifecycle hooks. The two status displays
may therefore disagree briefly. See the [official integration documentation](https://herdr.dev/docs/integrations/).

On each Codex execution host:

```sh
# If already installed, keep your existing Herdr integration.
herdr integration install codex
cd /absolute/path/codex-mx-bridge
python3 bridge.py install-hooks
python3 bridge.py install-hooks --apply
```

Restart the Codex sessions and review the bridge hooks through `/hooks`.
The bridge installer preserves unrelated event groups, matchers, metadata, and
individual handlers, including Herdr handlers sharing a group. Re-running it
updates its own entries without duplicating them. Avoid running both installers
simultaneously; they do not share a cross-product configuration lock. Backups
permit recovery, and the bridge detects a changed file before its final write.
Recheck the merged file after upgrading or reinstalling Herdr's integration.

Run normal `codex` inside Herdr. The optional `bridge.py run -- codex` launcher
can add process liveness, but validate Herdr's detection and native resume in
your installed version if using a wrapper command. No change to Herdr's own
restore command is made by this project.

An inherited iTerm ID identifies an outer terminal, not a stable Herdr pane.
When `HERDR_ENV=1`, focus metadata is suppressed. If your version does not set
that marker, explicitly start the agent with `HERDR_ENV=1 codex` (or the wrapper)
so this bridge does not mistake the virtual pane for a direct iTerm session.
Detaching Herdr must not mark its agents closed: they still run in the server.

## Remote Linux setup

The Mac hosts the Logitech plugin. Linux hosts only Python and the hooks; it
does not need Logitech software, .NET, or an inbound HTTP port.

1. Configure an OpenSSH alias on the Mac, for example:

   ```sshconfig
   Host workbox
       HostName linux-desktop.example
       User your-linux-user
       Port 22
       IdentityFile ~/.ssh/id_ed25519
   ```

   Replace the example values. Verify the host key and authentication normally
   with `ssh workbox`. Load a passphrase-protected key in your SSH agent before
   starting the noninteractive collector. The bridge never disables host-key
   checks, stores a password, or forwards your SSH agent to Linux.

2. Copy or clone the complete project onto Linux. If using the extracted ZIP:

   ```sh
   # Run from the directory containing the extracted codex-mx-bridge folder.
   scp -r ./codex-mx-bridge workbox:~/codex-mx-bridge
   ssh workbox
   cd ~/codex-mx-bridge
   python3 --version
   python3 bridge.py install-hooks --apply
   codex
   # In Codex: review/trust bridge definitions with /hooks.
   ```

   Use Python 3.10+ and a Codex version with the documented hooks. Install
   Herdr's own Codex integration on Linux too if you want Herdr's native restore.
   Restart already-running Codex processes so they load the new configuration.

3. On the Mac, start the collector using the **absolute Linux script path**:

   ```sh
   cd /absolute/mac/path/codex-mx-bridge
   python3 bridge.py collect-ssh \
     --host workbox --alias linux-desktop \
     --remote-script /home/your-linux-user/codex-mx-bridge/bridge.py \
     --once
   ```

   This should exit 0. Then omit `--once` for continued collection:

   ```sh
   python3 bridge.py collect-ssh \
     --host workbox --alias linux-desktop \
     --remote-script /home/your-linux-user/codex-mx-bridge/bridge.py
   ```

   Leave it running in a separate local terminal or a persistent local Herdr
   pane. One collector per alias prevents competing snapshots. Use distinct
   aliases for different Linux hosts. `--interval` accepts 1–60 seconds.

   If Linux uses a custom bridge state directory or Python path:

   ```sh
   python3 bridge.py collect-ssh --host workbox --alias linux-desktop \
     --remote-script /home/your-linux-user/codex-mx-bridge/bridge.py \
     --remote-python /usr/bin/python3 \
     --remote-state /home/your-linux-user/custom-mx-state
   ```

4. Attach through either Herdr path you already use:

   ```sh
   herdr --remote workbox
   # Or:
   ssh workbox
   herdr
   ```

   Both keep Codex execution and hook writes on Linux. The bridge's SSH polling
   is independent of Herdr's transport and does not need to inspect Herdr's
   internal connection. These execution-location semantics are described in
   [Herdr's remote-work guide](https://herdr.dev/docs/how-to-work/).

## Connection and status semantics

* Pull-only: the Mac initiates ordinary SSH commands. No reverse tunnel,
  remote HTTP server, copied private key, or network-facing bridge daemon.
* Export uses the same Python source on Linux. The collector runs `python3
  /absolute/path/bridge.py export` through OpenSSH with shell-quoted arguments.
  Use a simple SSH config alias; put ports, proxy jumps, and identity settings
  in SSH config rather than extra collector arguments.
* A 12-second subprocess deadline and SSH connection/keepalive limits bound a
  failed poll. Failure marks cached rows `OFFLINE` immediately after the poll
  returns. If the collector itself disappears, the plugin marks them offline
  15 seconds after the last success, even if they previously said `CLOSED`.
* Snapshot ages and remaining liveness intervals are transferred as durations,
  avoiding dependence on synchronized Mac/Linux wall clocks. Network/request
  elapsed time is conservatively deducted. System clock jumps on either host
  can still affect local expiry and require a fresh event.
* A dropped connection loses intermediate events; reconnect retrieves the
  current snapshot. There is no durable event replay or exactly-once delivery.
* Export excludes other imported hosts, so collection loops do not recurse.
  Source labels namespace remote rows from local rows with identical session IDs.
* Agent hooks continue on Linux while the Mac sleeps, disconnects, or detaches
  Herdr. The Mac shows the next snapshot when collection resumes.
* Interactive password/MFA prompts are intentionally unavailable in background
  collection (`BatchMode=yes`). Complete authentication separately; the bridge
  cannot inherit Herdr-specific credentials unless ordinary OpenSSH can use them.

## What remains unsupported

This version displays remote Codex status but does not select a particular
Herdr pane, start Herdr, attach clients, send prompts, approve requests, or type
into an agent terminal. Those actions require a separate Herdr-aware adapter
with verified identity mapping and explicit connection behavior. See the
[extension assessment](HERDR-EXTENSION-ASSESSMENT.md).

Linux-side iTerm metadata is never used to control a Mac terminal. Remote
snapshots do not include prompts, tool inputs/results, full working paths, or
assistant message text, but project labels and session IDs are still private
metadata. SSH encryption and local user-only file permissions protect transport
and storage; processes running as your account can still read or alter them.
