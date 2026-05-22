#!/usr/bin/env bash
# AutoAFK Linux launcher — mirrors start.bat.
# Requirement 8.
#
# Executable bit reminder: this script must be committed with the executable
# bit set. Maintainers: run `git update-index --chmod=+x start.sh` once when
# committing from Windows. End users on a fresh checkout where the bit was
# lost can restore it with `chmod +x start.sh` (see README).

set -e
cd "$(dirname "$0")"   # Run from repo root regardless of caller's pwd.

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is not installed or not in PATH"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

# Quick sanity check that deps are installed.
if ! python3 -c 'import customtkinter' >/dev/null 2>&1; then
    echo "Dependencies not found! Run ./install.sh first."
    exit 1
fi

echo "Starting AutoAFK..."
exec python3 main.py "$@"
