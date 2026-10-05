#!/usr/bin/env bash
# Installs deej-linux into its own venv and runs it as a systemd user service.
# Re-run after pulling changes to update. No root needed.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
PREFIX="$HOME/.local/share/deej-linux"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/deej/config.yaml"

if ! python3 -c "import ensurepip, venv" 2>/dev/null; then
    echo "python3 venv support is missing. Install it with:  sudo apt install python3-venv" >&2
    exit 1
fi

echo "==> installing into $PREFIX/venv"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet --upgrade "$SRC"

if [ -e "$CONFIG" ]; then
    echo "==> keeping existing config $CONFIG"
else
    "$PREFIX/venv/bin/deej-linux" --write-config
    echo "    edit com_port and slider_mapping there; changes apply live"
fi

echo "==> installing systemd user service"
mkdir -p "$UNIT_DIR"
install -m 644 "$SRC/systemd/deej-linux.service" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable deej-linux.service
systemctl --user restart deej-linux.service

if ! id -nG | grep -qw dialout; then
    echo
    echo "!! $USER is not in the dialout group, so the serial port won't be readable. Run:"
    echo "     sudo usermod -aG dialout $USER"
    echo "   then log out and back in (or reboot)."
fi

echo
echo "done. status: systemctl --user status deej-linux"
echo "      logs:   journalctl --user -u deej-linux -f"
