#!/usr/bin/env bash
# Install the four school Google CLIs: one venv, four ~/.local/bin symlinks.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${GSUITE_VENV:-$HOME/.venv-gsuite}"
BIN="${GSUITE_BIN:-$HOME/.local/bin}"

python3 -m venv "$VENV"
"$VENV/bin/pip" -q install --upgrade pip
"$VENV/bin/pip" -q install -e "$HERE"
mkdir -p "$BIN"
for cmd in gmail gdrive gdocs gcal; do
  ln -sf "$VENV/bin/$cmd" "$BIN/$cmd"
done
echo "installed: gmail, gdrive, gdocs, gcal  ->  $VENV"
"$BIN/gmail" --help >/dev/null && echo ok
