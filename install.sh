#!/bin/sh
set -eu

REPOSITORY_URL="https://github.com/siefbisnes/Panel.git"
INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/panel"
VENV="$INSTALL_ROOT/venv"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/panel"
INSTALL_GUI=0

usage() {
    cat <<'EOF'
Usage: install.sh [--gui]

Install Panel into a private virtual environment under ~/.local/share.
Pass --gui to install the optional PyGObject dependency as well.
EOF
}

for argument in "$@"; do
    case "$argument" in
        --gui) INSTALL_GUI=1 ;;
        --help|-h) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$argument" >&2; usage >&2; exit 2 ;;
    esac
done

if ! command -v python3 >/dev/null 2>&1; then
    printf 'Error: Python 3 is required. Install Python 3.10 or newer first.\n' >&2
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    printf 'Error: Git is required to install Panel from GitHub.\n' >&2
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    printf 'Error: Python 3.10 or newer is required.\n' >&2
    exit 1
fi

if [ -e "$LAUNCHER" ] || [ -L "$LAUNCHER" ]; then
    if [ ! -L "$LAUNCHER" ] || [ "$(readlink "$LAUNCHER")" != "$VENV/bin/panel" ]; then
        printf 'Error: %s already exists and is not this install. Move it aside before continuing.\n' "$LAUNCHER" >&2
        exit 1
    fi
fi

mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV"
fi

if [ "$INSTALL_GUI" -eq 1 ]; then
    PACKAGE_SPEC="panel[gui] @ git+$REPOSITORY_URL"
else
    PACKAGE_SPEC="panel @ git+$REPOSITORY_URL"
fi

"$VENV/bin/python" -m pip install --upgrade "$PACKAGE_SPEC"
if [ ! -L "$LAUNCHER" ]; then
    ln -s "$VENV/bin/panel" "$LAUNCHER"
fi

printf '\nPanel is installed. Run: %s/panel\n' "$BIN_DIR"
case ":${PATH:-}:" in
    *":$BIN_DIR:"*) ;;
    *) printf 'Add this to your shell startup file if the command is not found:\n  export PATH="$BIN_DIR:$PATH"\n' ;;
esac
if [ "$INSTALL_GUI" -eq 1 ]; then
    printf 'The GTK interface can be launched with: panel gui\n'
else
    printf 'For the GTK interface, install GTK 4 and PyGObject system dependencies, then rerun with --gui.\n'
fi
