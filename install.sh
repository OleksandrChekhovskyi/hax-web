#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
COMMAND_TARGET="$HOME/.local/bin/hax-web"
SKILL_TARGET="$CONFIG_HOME/hax/skills/web"

if ! command -v python3 >/dev/null; then
    echo "error: python3 is required" >&2
    exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 9))'; then
    echo "error: Python 3.9 or newer is required" >&2
    exit 1
fi

check_target() {
    local source=$1
    local target=$2

    if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
        return
    fi
    if [ -e "$target" ] || [ -L "$target" ]; then
        echo "error: $target already exists" >&2
        exit 1
    fi
}

link_target() {
    local source=$1
    local target=$2

    if [ -L "$target" ] && [ "$(readlink "$target")" = "$source" ]; then
        echo "skip $target"
        return
    fi
    mkdir -p "$(dirname "$target")"
    ln -s "$source" "$target"
    echo "link $target"
}

check_target "$SCRIPT_DIR/hax-web" "$COMMAND_TARGET"
check_target "$SCRIPT_DIR/skills/web" "$SKILL_TARGET"
link_target "$SCRIPT_DIR/hax-web" "$COMMAND_TARGET"
link_target "$SCRIPT_DIR/skills/web" "$SKILL_TARGET"

"$COMMAND_TARGET" --version
case ":${PATH:-}:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "note: add $HOME/.local/bin to PATH" ;;
esac
echo "restart hax to load the web skill"
