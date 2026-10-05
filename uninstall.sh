#!/usr/bin/env bash
# Removes the deej-linux service and venv. Leaves your config in ~/.config/deej alone.
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

systemctl --user disable --now deej-linux.service 2>/dev/null || true
rm -f "$UNIT_DIR/deej-linux.service"
systemctl --user daemon-reload
rm -rf "$HOME/.local/share/deej-linux"
echo "deej-linux removed (config kept in ${XDG_CONFIG_HOME:-$HOME/.config}/deej)"
