#!/usr/bin/env python3.15
"""Build with the real SDK; optional package and development link installation."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sdk", type=Path, default=os.environ.get("PLUGIN_API_PATH",
        "/Applications/Utilities/LogiPluginService.app/Contents/MonoBundle/PluginApi.dll"))
    p.add_argument("--link", action="store_true", help="Install a macOS development .link")
    p.add_argument("--pack", action="store_true", help="Pack and verify with LogiPluginTool")
    args = p.parse_args()
    sdk = Path(args.sdk).expanduser().resolve()
    if not sdk.is_file():
        p.error("PluginApi.dll missing. Install Options+, or use --sdk /absolute/path/PluginApi.dll")
    subprocess.run(["dotnet", "build", str(ROOT/"plugin/CodexMxPlugin.csproj"), "-c", "Release",
                    "-p:PluginApiPath=" + str(sdk)], check=True, cwd=ROOT)
    package = ROOT/"plugin/bin/Release/package"
    if args.link:
        if sys.platform != "darwin":
            p.error("--link installs only on macOS")
        plugins = Path.home()/"Library/Application Support/Logi/LogiPluginService/Plugins"
        plugins.mkdir(parents=True, exist_ok=True)
        (plugins/"CodexMxPlugin.link").write_text(str(package) + "\n", encoding="utf-8")
        print("Development link installed. Restart Logi Plugin Service in Options+.")
    if args.pack:
        tool = shutil.which("logiplugintool")
        if not tool:
            p.error("Install LogiPluginTool 6.1.4.22672, and add its tool directory to PATH")
        output = ROOT/"CodexMx_0_2_0.lplug4"
        subprocess.run([tool, "pack", str(package), str(output)], check=True)
        subprocess.run([tool, "verify", str(output)], check=True)
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
