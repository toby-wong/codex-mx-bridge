#!/usr/bin/env python3.15
"""Publish tested assets and advance the formula, without replacing released bytes."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from release import REPOSITORY, checksum


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def publish(directory):
    record = json.loads((directory / "release.json").read_text())
    tag, version, assets = record["tag"], record["version"], record["assets"]
    if (record.get("repository") != REPOSITORY or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) or
            tag != "v" + version or set(assets) !=
            {f"codex-mx-bridge-{version}.tar.gz", f"CodexMx_{version.replace('.', '_')}.lplug4"}):
        raise ValueError("Unexpected release manifest")
    for name, digest in assets.items():
        if checksum(directory / name) != digest:
            raise ValueError(f"Checksum mismatch: {name}")
    candidate = (directory / "codex-mx-bridge.rb").read_text()
    expected_url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/codex-mx-bridge-{version}.tar.gz"
    if (f'url "{expected_url}"' not in candidate or f'version "{version}"' not in candidate or
            f'sha256 "{assets[f"codex-mx-bridge-{version}.tar.gz"]}"' not in candidate):
        raise ValueError("The tested formula does not match the release")
    releases = json.loads(run(["gh", "api", f"repos/{REPOSITORY}/releases", "--paginate",
                               "--slurp"], capture_output=True).stdout)
    existing = next((release for page in releases for release in page if release["tag_name"] == tag), None)
    names = [*assets, "SHA256SUMS"]
    if existing is None:
        with tempfile.TemporaryDirectory(prefix="mx-release-notes-") as folder:
            notes = Path(folder) / "notes.md"
            notes.write_text(
                f"Install the complete bridge, pet importer, settings app, and prebuilt Logitech plugin:\n\n"
                "```sh\n"
                f"brew tap toby-wong/codex-mx-bridge https://github.com/{REPOSITORY}\n"
                "brew install codex-mx-bridge\n"
                "codex-mx setup\n"
                "```\n\n"
                "For another client, use `--client claude`, `--client pi`, or "
                "`--client kiro --agent-config /path/to/profile.json`. "
                "Setup preserves existing registered clients and display settings.\n\n"
                "Logi Options+ and selected agent CLIs are installed separately. "
                "Codex hook trust and button assignments need their native UI. "
                "Community artwork is installed separately through the settings app.\n")
            run(["gh", "release", "create", tag, "--repo", REPOSITORY, "--verify-tag", "--draft",
                 "--title", f"Codex MX Bridge {version}", "--notes-file", str(notes),
                 *[str(directory / name) for name in names]])
    elif existing["draft"]:
        run(["gh", "release", "upload", tag, "--repo", REPOSITORY, "--clobber",
             *[str(directory / name) for name in names]])
    else:
        with tempfile.TemporaryDirectory(prefix="mx-released-assets-") as folder:
            run(["gh", "release", "download", tag, "--repo", REPOSITORY, "--dir", folder,
                 *[item for name in names for item in ("--pattern", name)]])
            if any(checksum(Path(folder) / name) != checksum(directory / name) for name in names):
                raise ValueError("Published assets differ; create a new version instead of replacing a release")
    destination = Path("Formula/codex-mx-bridge.rb")
    current = re.search(r'^\s*version "([0-9.]+)"', destination.read_text(), re.M) if destination.exists() else None
    latest = not current or tuple(map(int, current[1].split("."))) <= tuple(map(int, version.split(".")))
    # Expose assets before pointing Homebrew at them. Reruns can finish a failed formula push.
    run(["gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false",
         "--latest=" + str(latest).lower()])
    if latest:
        destination.parent.mkdir(exist_ok=True)
        shutil.copyfile(directory / "codex-mx-bridge.rb", destination)
        run(["git", "add", "--", str(destination)])
        changed = subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode
        if changed == 1:
            run(["git", "-c", "user.name=github-actions[bot]",
                 "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                 "commit", "-m", f"Publish Homebrew formula for {tag}", "--", str(destination)])
            run(["git", "push", "origin", "HEAD"])
        elif changed:
            raise ValueError("Cannot inspect the formula diff")
    print(f"Published {tag}; Homebrew formula {'updated' if latest else 'kept at its newer version'}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path("dist"))
    publish(parser.parse_args().artifacts)
