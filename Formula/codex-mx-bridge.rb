require "json"
require "shellwords"

class CodexMxBridge < Formula
  desc "Agent status and animated pets for Logitech MX Creative Console"
  homepage "https://github.com/toby-wong/codex-mx-bridge"
  url "https://github.com/toby-wong/codex-mx-bridge/releases/download/v0.4.1/codex-mx-bridge-0.4.1.tar.gz"
  version "0.4.1"
  sha256 "0491ed3fe108d72d7c96c2eb0a8e69a11e1932a51104d9905d5dbe5958cbde88"
  license "MIT"

  depends_on "pillow"
  depends_on "python@3.15"

  def install
    libexec.install buildpath.children
    python = Formula["python@3.15"].opt_bin/"python3.15"
    (libexec/"homebrew.json").write JSON.generate(
      schema_version: 1,
      python: python.to_s,
      root: opt_libexec.to_s,
    )
    (bin/"codex-mx").write <<~SH
      #!/bin/sh
      exec #{python.to_s.shellescape} #{(opt_libexec/"bridge.py").to_s.shellescape} "$@"
    SH
    (bin/"codex-mx").chmod 0755
  end

  def caveats
    <<~EOS
      Activate the bridge for this user:
        codex-mx setup

      On macOS, Logi Options+ and at least one selected agent CLI must already
      be installed. To install missing Options+ as part of setup:
        codex-mx setup --install-options

      Select other clients with --client claude, --client pi, or
      --client kiro --agent-config /path/to/profile.json.
      Existing registered clients are retained when setup is run again.

      Open the settings and pet app:
        codex-mx settings

      After brew upgrade, run codex-mx setup to activate the new release.
      Codex hook trust and Logitech button assignments still require their UI.
      Config, pets, and active source copies stay in your user directories.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/codex-mx --version")
    system bin/"codex-mx", "--state-dir", testpath/"state", "demo"
    state = JSON.parse((testpath/"state/state.json").read)
    assert_equal 1, state.fetch("schema_version")
    assert_operator state.fetch("rows").length, :>, 0
    system bin/"codex-mx", "setup", "--hooks-only", "--dry-run",
           "--prefix", testpath/"install", "--codex-home", testpath/"codex"
    assert_path_exists libexec/"mxbridge/settings_web/index.html"
    assert_path_exists libexec/"prebuilt/CodexMx/bin/CodexMxPlugin.dll"
    python = Formula["python@3.15"].opt_bin/"python3.15"
    system python, "-c", "from PIL import Image, features; assert features.check('webp')"
    system python, "-c",
           "import sys; sys.path.insert(0, #{libexec.to_s.to_json}); " \
           "from mxbridge.distribution import validate_plugin; validate_plugin(#{libexec.to_s.to_json})"
  end
end
