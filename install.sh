#!/usr/bin/env bash
set -euo pipefail

# Self-contained installer for macOS/Linux
# Creates venv, installs mirrorme + Playwright browser binaries.

VENV_DIR=".venv"

echo "[*] Creating virtualenv at ${VENV_DIR} ..."
python3 -m venv "${VENV_DIR}"
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

echo "[*] Upgrading pip..."
python -m pip install -U pip

echo "[*] Installing package (editable) ..."
pip install -e .

echo "[*] Installing Playwright browsers (Chromium) ..."
python -m playwright install chromium

echo
echo "[*] Done. Activate and run:"
echo "    source ${VENV_DIR}/bin/activate"
echo "    mirrorme https://example.com --out site_mirror"

