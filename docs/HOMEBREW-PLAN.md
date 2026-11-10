# Homebrew distribution

## Install and activation

Use this repository as an explicit-URL Homebrew tap. The formula installs
Python 3.15, Homebrew's Pillow, the bridge and settings app code, and the
Logitech plugin built by GitHub Actions. No .NET SDK or plugin build is needed
on an end user's machine.

`codex-mx setup` activates the installation for the current user. It reuses
the existing configuration merging and validation, registers selected agent
clients, links the prebuilt plugin, and creates the Finder launcher on macOS.
An existing installation's registered clients are retained on upgrades.
Kiro still requires an explicit existing profile on first setup.

Active source and plugin files are copied to an immutable user-local release.
Hook definitions never point into a removable Homebrew Cellar version.
Homebrew owns the runtime; setup does not install pip dependencies into it.
Existing display settings, pets, sessions, and terminal bindings are retained.
Codex hook trust and Logitech device assignments remain native UI steps.

## Release automation

- Pull requests and pushes run the portable tests on macOS and Linux.
- Version tags build and verify the plugin using the pinned official
  LogiPluginTool SDK. Vendor SDK assemblies and community pets are excluded.
- Build a checksummed distribution archive and standalone plugin package.
- Install and test the candidate formula with Homebrew on macOS and Linux.
- Publish the tested GitHub release and commit its formula to `Formula/` on
  the default branch. Use the repository's scoped Actions token; no separate
  tap or personal publishing token is required.
- Reject inconsistent versions and changed assets for an existing release.

## Verification

Test prebuilt setup without a .NET SDK, source-installer compatibility,
configuration preservation, repeat setup, and activation after package
relocation. Exercise a real Homebrew install and `brew test`, publish the
first release through Actions, and verify the public formula and assets.
