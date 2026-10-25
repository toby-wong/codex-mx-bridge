#!/usr/bin/env bash
# User-local Python bootstrap; the Python installer handles all project changes.
set -euo pipefail
umask 077
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
python_bin="${MX_PYTHON:-}"
dry_run=0
no_downloads=0
for ((i=1; i<=$#; i++)); do
    arg="${!i}"
    case "$arg" in
        --python)
            next=$((i+1))
            if (( next > $# )); then echo '--python requires an executable path' >&2; exit 2; fi
            python_bin="${!next}"
            ;;
        --dry-run) dry_run=1 ;;
        --no-downloads) no_downloads=1 ;;
        --help|-h)
            cat <<'HELP'
Usage: bash install.sh [options]
  --hooks-only          Linux/server hooks and export; no Logitech/.NET install
  --prefix PATH         Install location (default: ~/.local/share/codex-mx-bridge)
  --codex-home PATH     Codex config location (defaults to CODEX_HOME or ~/.codex)
  --client NAME         codex (default), claude, or kiro; repeat for multiple
  --claude-settings P   Claude settings file (default: CLAUDE_CONFIG_DIR/settings.json)
  --agent-config PATH   Existing Kiro agent profile; repeat to select profiles
  --kiro-format v2|v3   Kiro hook object (default) or inline array; no migration
  --instance NAME      Optional namespace for otherwise identical session IDs
  --python PATH         Use this stable Python 3.15 executable
  --sdk PATH            Override the macOS PluginApi.dll location
  --install-options     Install missing Options+ with an existing Homebrew
  --with-pets           Install the optional local sprite-sheet importer (Mac)
  --pet-sheet PATH      Import and enable this PNG/WebP atlas; implies --with-pets
  --pet-name NAME       Name for the imported pet (default: codex-pet)
  --pet-layout PATH     Layout JSON for another sprite version
  --motion on|off       Enable animation or use a still status pose
  --no-downloads        Use only existing Python 3.15 and .NET 8 installations
  --dry-run             Show the plan; no downloads or installation changes

Downloads a private uv/Python runtime when needed. The installer copies the
project to a stable location, creates an isolated Python 3.15 environment,
preserves other hooks, checks each selected client, and (on Mac) builds and links
the Logitech plugin. Selected CLIs must already be installed. Codex hook
enablement applies only when Codex is selected. Hook trust and Options+ button
assignments are manual.
HELP
            exit 0 ;;
    esac
done
case "$(uname -s)" in
    Darwin|Linux) ;;
    *) echo 'Run this installer on your Mac, or on Linux with --hooks-only.' >&2; exit 2 ;;
esac
check_python() {
    "$1" -c 'import sys; sys.exit(not (sys.version_info[:2] == (3,15) and sys.version_info.releaselevel == "final"))' >/dev/null 2>&1
}
if [[ -n "$python_bin" ]]; then
    if ! check_python "$python_bin"; then echo '--python must point to stable Python 3.15.' >&2; exit 2; fi
else
    for candidate in python3.15 /Library/Frameworks/Python.framework/Versions/3.15/bin/python3.15 python3; do
        if check_python "$candidate"; then python_bin="$candidate"; break; fi
    done
fi
if [[ -z "$python_bin" ]]; then
    if (( dry_run )); then
        echo 'Plan only: obtain private Python 3.15; copy bridge; preserve/enable hooks; verify install.'
        echo 'On macOS: locate Options+, obtain .NET 8 if needed, build and link the plugin.'
        echo 'No changes made. Run again without --dry-run to install.'
        exit 0
    fi
    if (( no_downloads )); then echo 'Python 3.15 is missing; supply --python PATH or allow downloads.' >&2; exit 2; fi
    runtime_root="${MX_BOOTSTRAP_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/codex-mx-bridge-runtime}"
    mkdir -p -- "$runtime_root"
    uv_bin="$runtime_root/uv/uv"
    if [[ ! -x "$uv_bin" ]]; then
        echo 'Installing private uv 0.13.5 without changing shell settings...'
        download_file="$(mktemp "${TMPDIR:-/tmp}/codex-mx-uv.XXXXXX")"
        trap 'rm -f -- "$download_file"' EXIT
        curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
            https://astral.sh/uv/0.13.5/install.sh -o "$download_file"
        UV_UNMANAGED_INSTALL="$runtime_root/uv" sh "$download_file"
        rm -f -- "$download_file"
        trap - EXIT
    fi
    export UV_PYTHON_INSTALL_DIR="$runtime_root/python"
    export UV_CACHE_DIR="$runtime_root/cache"
    "$uv_bin" python install 3.15 --no-bin --no-config
    python_bin="$("$uv_bin" python find 3.15 --managed-python --no-config)"
    if ! check_python "$python_bin"; then echo 'Python download did not provide stable 3.15.' >&2; exit 2; fi
fi
export PYTHONDONTWRITEBYTECODE=1
exec "$python_bin" "$source_dir/scripts/install_local.py" "$@"
