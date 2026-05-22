#!/usr/bin/env bash
# AutoAFK Linux installer — mirrors install.bat.
#
# Executable bit: this file must be checked into git with the executable
# bit set. Maintainers committing from a non-POSIX environment should run:
#     git update-index --chmod=+x install.sh
# End users who receive a copy with the bit lost can restore it with:
#     chmod +x install.sh

set -e
cd "$(dirname "$0")"

echo "================================================================"
echo "                AutoAFK - Linux Installation"
echo "================================================================"
echo

# 1. Python check
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 is not installed or not in PATH."
    echo "        Please install Python 3.8-3.12 from your distribution"
    echo "        (e.g. 'sudo pacman -S python' on CachyOS/Arch)."
    exit 1
fi

PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "[1/4] Detected Python $PYV"
echo

# 2. Pip upgrade (best-effort; do not abort on failure)
echo "[2/4] Upgrading pip..."
python3 -m pip install --upgrade pip --quiet \
    || echo "      [WARNING] pip upgrade failed; continuing anyway."
echo

# 3. Dependencies
echo "[3/4] Installing dependencies from requirements.txt..."
python3 -m pip install -r requirements.txt
echo "      Dependencies installed."
echo

# 4. Settings file
echo "[4/4] Setting up configuration..."
if [ ! -f settings.ini ]; then
    if [ -f settings.ini.example ]; then
        cp settings.ini.example settings.ini
        echo "      Created settings.ini from settings.ini.example."
        echo "      [IMPORTANT] Edit settings.ini and configure your device."
    else
        echo "      [WARNING] settings.ini.example not found; skipping."
    fi
else
    echo "      settings.ini already exists; preserved unchanged."
fi
echo

# 5. ADB check
if ! command -v adb >/dev/null 2>&1; then
    echo "[ERROR] adb is not on \$PATH."
    echo "        Install android-tools via your system package manager."
    echo "        Example (CachyOS/Arch): sudo pacman -S android-tools"
    exit 1
fi

echo "================================================================"
echo "                  Installation Complete"
echo "================================================================"
echo "Next steps:"
echo "  1. Connect your emulator/device."
echo "  2. Run 'adb devices' to confirm the device is reachable."
echo "  3. Edit settings.ini and set the ADB port if needed."
echo "  4. Run ./start.sh (or 'python3 main.py')."
