#!/usr/bin/env bash
# Upgrade an existing installation from this checkout using its Python runtime.
set -euo pipefail
umask 077
upgrade_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
upgrade_prefix="${XDG_DATA_HOME:-$HOME/.local/share}/codex-mx-bridge"
upgrade_python="${MX_PYTHON:-}"
for ((upgrade_i=1; upgrade_i<=$#; upgrade_i++)); do
    upgrade_arg="${!upgrade_i}"
    case "$upgrade_arg" in
        --prefix|--python)
            upgrade_next=$((upgrade_i+1))
            if (( upgrade_next > $# )); then
                echo "$upgrade_arg requires a path" >&2
                exit 2
            fi
            if [[ "$upgrade_arg" == --prefix ]]; then
                upgrade_prefix="${!upgrade_next}"
            else
                upgrade_python="${!upgrade_next}"
            fi
            upgrade_i=$upgrade_next
            ;;
        --prefix=*) upgrade_prefix="${upgrade_arg#*=}" ;;
        --python=*) upgrade_python="${upgrade_arg#*=}" ;;
        --help|-h)
            cat <<'HELP'
Usage: bash update.sh [options]
  --dry-run             Preview the upgrade without changing files or services
  --prefix PATH         Existing install directory
  --python PATH         Override the installed Python 3.15 runtime
  --sdk PATH            Override automatic compatible SDK selection
  --no-downloads        Require existing Python/.NET dependencies
  --no-restart          Leave Logi Plugin Service running; reload it manually
  --bind-herdr SOCKET   Bind a local Herdr server to this outer iTerm2 pane
  --iterm-id ID         Explicit outer iTerm2 ID for --bind-herdr
  --state-dir PATH      Bridge state directory for the optional terminal binding

Installs the source in this checkout; it does not pull or reset Git.
Preserves existing pet settings, agent state, bindings, and button assignments.
On Mac, rebuilds the plugin and restarts Logi Plugin Service after success.
Run --bind-herdr from the outer local iTerm2 shell, or supply --iterm-id.
Codex hook trust still needs review in /hooks after the upgrade.
HELP
            exit 0 ;;
    esac
done
if [[ -z "$upgrade_python" ]]; then
    upgrade_python="$upgrade_prefix/venv-3.15/bin/python"
fi
if ! "$upgrade_python" -c 'import sys; sys.exit(not (sys.version_info[:2] == (3,15) and sys.version_info.releaselevel == "final"))' >/dev/null 2>&1; then
    echo 'Existing Python 3.15 runtime unavailable. Supply --python PATH, or run bash install.sh first.' >&2
    exit 2
fi
export PYTHONDONTWRITEBYTECODE=1
exec "$upgrade_python" "$upgrade_root/scripts/update_local.py" "$@"
