#!/usr/bin/env python3.15
"""Install and test a release archive through a temporary Homebrew tap."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.release import checksum, formula


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    record = json.loads((args.artifacts / "release.json").read_text())
    name = f"codex-mx-bridge-{record['version']}.tar.gz"
    archive = (args.artifacts / name).absolute()
    if checksum(archive) != record["assets"][name]:
        parser.error("Release archive checksum mismatch")
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
               HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK="1", HOMEBREW_NO_ENV_HINTS="1",
               HOMEBREW_NO_AUTOREMOVE="1", HOMEBREW_DEVELOPER="1")
    existing = subprocess.run(["brew", "list", "--formula", "--versions", "codex-mx-bridge"],
                              env=env, capture_output=True, text=True)
    if existing.returncode == 0 and existing.stdout.strip():
        parser.error("codex-mx-bridge is already installed; use a clean runner for the candidate test")
    tap = "codex-mx-ci/test-" + uuid.uuid4().hex[:8]
    qualified = tap + "/codex-mx-bridge"
    created = False
    try:
        subprocess.run(["brew", "tap-new", "--no-git", tap], env=env, check=True)
        created = True
        path = Path(subprocess.check_output(["brew", "--repository", tap], env=env, text=True).strip())
        (path / "Formula/codex-mx-bridge.rb").write_text(
            formula(archive.as_uri(), checksum(archive), record["version"]))
        subprocess.run(["brew", "install", "--build-from-source", qualified], env=env, check=True)
        subprocess.run(["brew", "test", qualified], env=env, check=True)
        print("Homebrew installation, setup preview, runtime, pet codec, and plugin checks passed.")
    finally:
        if created:
            info = subprocess.run(["brew", "info", "--json=v2", qualified], env=env,
                                  capture_output=True, text=True)
            if info.returncode == 0 and json.loads(info.stdout)["formulae"][0]["installed"]:
                subprocess.run(["brew", "uninstall", qualified], env=env, check=True)
            subprocess.run(["brew", "untap", tap], env=env, check=True)


if __name__ == "__main__":
    main()
