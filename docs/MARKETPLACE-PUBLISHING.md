# Logitech Marketplace publishing assessment

Checked 25 October 2026 against Logitech's public documentation and this
checkout. Publication is feasible through the existing C# plugin route.
The package builds and verifies, but the current source-install workflow
still needs a public distribution and support path.

## Submission route

1. Test the release on its claimed hardware and operating systems.
2. Build and verify the `.lplug4` using LogiPluginTool.
3. Sign in at [Marketplace Contribute](https://marketplace.logitech.com/contribute),
   accept the developer agreement, upload the plugin and describe it.
4. Logitech reviews new submissions and every update before publication.
   Its guidelines give no guaranteed turnaround; they suggest following up
   after ten working days without a response. [1][2]

The public submission page was inspected without signing in. Exact fields,
asset limits and any additional checks behind the login remain unverified.
No submission or agreement acceptance was performed for this investigation.

## Current readiness

| Area | Finding and required work |
| --- | --- |
| Package | Fresh `.lplug4` packing and verification passed with LogiPluginTool 6.1.4.22672. This verifies package structure, not Marketplace approval. |
| Metadata | `plugin/package/metadata/LoupedeckPackage.yaml` lacks the documented mandatory `supportPageUrl`, `license`, and `licenseUrl` fields. Add reachable public support and license URLs; a public `homePageUrl` would also help. [3] |
| Identity | The current permanent ID is `CodexMx`, displayed as “Codex MX Bridge.” Decide whether to retain that branding before submission: Logitech says the ID cannot change after publication. [3] |
| Platform and device claims | The package has a Mac binary entry only. Treat this as a macOS release, with Linux as the separate remote bridge. Verify the current `LoupedeckExtendedFamily` device declaration with Logitech for MX Creative Console; the metadata guide still documents older device names. Do not claim all devices or a minimum version based only on a successful build. |
| Companion setup | The package contains the C# plugin, icon and focus script. It does not contain Python, bridge scripts, hooks or pet packs. A clean Marketplace install therefore cannot collect chat state on its own. Provide an accessible companion download and setup guide, and test the complete installation. |
| Public links | Anonymous GitHub API and README requests confirmed that the repository is already public and Issues are enabled. Its setup documentation can be linked from the listing and metadata. Public links must remain reachable; no visibility change is needed. [2] |
| License and privacy | The source has an MIT license. Logitech additionally requires a Developer EULA and specifies MIT/Apache-2.0 requirements for included open-source content. Inventory anything added to the package and prepare a privacy statement covering local IDs, names, terminal identifiers and optional SSH collection. Confirm terms before submission. [2] |
| Listing assets | The package icon is original generated artwork. The README preview includes Logitech product art and the locally imported pet. Use original or permission-cleared listing imagery with synthetic chat names; the existing preview is not evidence of redistribution rights. |
| Device validation | Add a clean-machine install/uninstall test and physical checks for paging, all three recent views, label reload, local focus and pet rendering. Existing automated checks and runtime render logs do not establish LCD legibility or correct physical focus. |

## Recommended first release

The missing metadata can use the existing public project:

```yaml
supportPageUrl: https://github.com/toby-wong/codex-mx-bridge/issues
license: MIT
licenseUrl: https://github.com/toby-wong/codex-mx-bridge/blob/main/LICENSE
homePageUrl: https://github.com/toby-wong/codex-mx-bridge
```

These are proposed fields for the submission preparation; this investigation
has not changed the package metadata.

Keep the current macOS plugin architecture and supply an explicit companion
setup flow for the chosen CLI clients. Document Python setup, hook review,
nine slot assignments, the paging control, optional Herdr binding, and
optional remote collection. The listing should describe Codex, Claude Code
and Kiro CLI status, configurable captions, and optional imported pets.

For a later integrated installer, the SDK documents `Plugin.Install()` and
`Plugin.Uninstall()` for application-side resources. Its plugin-status API
can show missing-companion diagnostics with a setup link. These are supported
building blocks, but packaging the Python runtime or editing client hooks
still needs a deliberate installation and removal design. [4][5]

Do not assume that dropping a default profile into this package automatically
assigns its buttons. The SDK limits bundled default application profiles to
application plugins; this plugin declares `HasNoApplication = true`. A tested
setup guide is sufficient for investigation; explore an exported companion
profile separately if desired. The documented device filenames are
`DefaultProfile70.lp5` for the keypad and `DefaultProfile71.lp5` for the
dialpad when the default-profile mechanism applies. [6]

Preserve `CodexMx` if keeping the current identity, and increment the version
before a public release. The current `0.3.0` development artifacts have changed
without a public Marketplace version history. Build the public candidate from
a tagged checkout, include the intended license/EULA, and re-run packing,
verification and device acceptance against those exact bytes.

## Validation from this investigation

* 118 Python tests and 211 C# checks passed.
* The release build completed with zero warnings/errors.
* `CodexMx_0_3_0.lplug4` packed and verified successfully.
* Inspection confirmed that Python, CLI hook installers, pet frames and the
  host's `PluginApi.dll` are absent from the package.
* No repository visibility, support account or Marketplace listing was changed.

## Primary sources

[1] [Distributing the Plugin](https://logitech.github.io/actions-sdk-docs/csharp/plugin-development/distributing-the-plugin/)
— submission route, packaging and verification.

[2] [Marketplace Approval Guidelines](https://logitech.github.io/actions-sdk-docs/marketplace-approval-guidelines/)
— review process, public links, compatibility, EULA, open-source and privacy requirements.
The linked [Developer Agreement](https://www.logitech.com/en-us/software/marketplace/developer-agreement.html)
is the agreement to review before submitting; its full terms were not analyzed here.

[3] [Plugin Structure](https://logitech.github.io/actions-sdk-docs/csharp/tutorial/plugin-structure/)
— metadata, mandatory fields, immutable ID and versioning.

[4] [Installation and Uninstallation](https://logitech.github.io/actions-sdk-docs/csharp/plugin-features/install-and-uninstall/)
— package installation and custom install/uninstall methods.

[5] [Plugin Status](https://logitech.github.io/actions-sdk-docs/csharp/plugin-features/plugin-status/)
— warning/error status and support links.

[6] [Default Application Profiles](https://logitech.github.io/actions-sdk-docs/csharp/plugin-features/default-application-profiles/)
— application-plugin restriction and device profile names.
