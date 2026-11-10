# Homebrew installation and releases

The repository is also a Homebrew tap. Install on macOS or Linux:

```sh
brew tap toby-wong/codex-mx-bridge https://github.com/toby-wong/codex-mx-bridge
brew install toby-wong/codex-mx-bridge/codex-mx-bridge
codex-mx setup
```

The fully qualified install command grants Homebrew trust to this formula.
If an older source installation takes precedence in your shell, activate the
Homebrew version with `$(brew --prefix)/bin/codex-mx setup`.

The formula includes the bridge, settings UI, Pi extension, and prebuilt
Logitech plugin. Homebrew supplies Python 3.15 and Pillow, including WebP
support. End users do not need a .NET SDK, Logitech build tools, or pip.
Community pet artwork is downloaded separately through **Pet library**.

On macOS, install Logi Options+ first, or let setup invoke its Homebrew cask:

```sh
codex-mx setup --install-options
```

Complete Logitech's own setup if prompted, then rerun bridge setup. The selected
agent CLIs must already be installed and authenticated. The bridge does not
replace or sign into agent clients.

## Agent clients

The first setup selects Codex by default. Select other clients explicitly:

```sh
codex-mx setup --client codex --client claude --client pi
codex-mx setup --client kiro --agent-config "$HOME/.kiro/agents/my-agent.json"
```

The Kiro profile must already exist. Each invocation preserves previously
registered scopes; `codex-mx setup` without explicit scope options reactivates
all registered clients on subsequent upgrades.

On a CloudDesktop with Homebrew, use the same formula and:

```sh
codex-mx setup --hooks-only --client pi
```

Linux automatically selects hooks/export mode. Existing SSH collection and
remote focus configuration remain separate; see [remote setup](REMOTE-AND-HERDR.md).
Setup prints the interpreter and script paths for the collector.

## Settings and activation

Open **Codex MX Bridge.app** from Finder, or run:

```sh
codex-mx settings
```

The **Theme** tab controls app colours and light/dark/system appearance.
Preferences in `~/.config/codex-mx-bridge/theme.json` hot reload independently
of the console display settings.

Setup copies the active source and plugin into
`~/.local/share/codex-mx-bridge/releases/`, then registers hooks and the plugin.
Agent hooks point to this immutable copy, so `brew cleanup` cannot remove
their entrypoint. The Python executable uses Homebrew's stable `opt` path.
Setup never writes pip packages into Homebrew's runtime.

Display settings stay in `~/.config/codex-mx-bridge/display.json` and hot
reload. Pet files, agent state, Herdr bindings, and existing non-bridge hooks
are preserved. Existing manifests and changed hook files are backed up.

Codex requires review of the hook entries in `/hooks`. Assign **Agent slot 1**
through **9** and the page actions in Options+. Setup cannot perform these
native trust and device-assignment steps. Use `--no-restart` to defer the
Logi Plugin Service restart.

## Updates and removal

```sh
brew update
brew upgrade codex-mx-bridge
codex-mx setup
```

Homebrew updates the available package; setup activates it for the current
user. Existing active copies are retained until then. Start fresh agent
sessions, review Codex hook changes, or use `/reload` in idle Pi sessions.
Use Homebrew updates for these installs; `update.sh` is for source installs.

Before uninstalling, remove this bridge's hook registrations with
`codex-mx install-hooks --remove --apply` for Codex, and the matching `--client`
and scope options for other registered clients. Remove `CodexMxPlugin.link`
from the Logi Plugin Service Plugins directory and restart that service.
Then run `brew uninstall codex-mx-bridge`. User config, pets, active copies,
and backups are retained for deliberate cleanup or reinstallation.

## Maintainer release process

Keep these versions equal:

- `mxbridge/__init__.py`
- `pyproject.toml`
- `plugin/package/metadata/LoupedeckPackage.yaml`

Commit and push the changes, then push their version tag:

```sh
git tag v0.4.2
git push origin v0.4.2
```

**Homebrew release** runs tests, builds against the official
`LogiPluginTool` **6.1.4.22672** .NET 8 SDK, and verifies the `.lplug4`.
It packages a distribution archive, records checksums, and runs actual
Homebrew installs and formula tests on macOS and Linux.

Only after those checks pass does it publish the GitHub release and commit
`Formula/codex-mx-bridge.rb` on the default branch with the archive URL and
SHA256. The same repository acts as the tap, so the workflow uses its scoped
`GITHUB_TOKEN` without an extra repository or personal publishing token.

The release contains the distribution `.tar.gz`, standalone `.lplug4`, and
`SHA256SUMS`. `PluginApi.dll`, the build SDK, and community pet artwork are
excluded. The library dependencies remain Homebrew-managed.

Use **Re-run failed jobs** to finish a failed formula push with the original
tested artifacts. **Run workflow → tag** rebuilds an existing version and may
finish a draft, but refuses to replace different bytes in an already published
release. Publish changed bytes under a new version.
Older releases do not downgrade the current Homebrew formula.

To verify a candidate locally:

```sh
python3.15 scripts/release.py build --tag v0.4.2
python3.15 scripts/brew_smoke.py --artifacts dist
```

The smoke test needs a machine without this formula already installed. It
creates a temporary tap, installs the candidate, runs `brew test`, and removes
only that candidate and tap afterward. It does not activate hooks or modify
the user's Logitech installation.
