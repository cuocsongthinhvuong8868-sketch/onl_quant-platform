#!/bin/bash
set -u

cd "$(dirname "$0")/.."

echo "======================================"
echo "Quant Platform - Setup (macOS/Linux)"
echo "Folder: $(pwd)"
echo "======================================"
echo

PY_BIN="python3"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  PY_BIN="python"
fi

if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  echo "[ERROR] Python not found (python3/python)."
  echo
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit 1
fi

echo "[1/4] Upgrade pip..."
"$PY_BIN" -m pip install --upgrade pip

echo
echo "[2/4] Install project dependencies..."
"$PY_BIN" -m pip install -r requirements.txt

echo
echo "[3/4] Install Playwright Chromium..."
"$PY_BIN" -m playwright install chromium

echo
echo "[4/4] Ensure launcher permissions..."
chmod +x Run_App.command Run_All_Updates.command setup/SETUP.command || true

echo
echo "[DONE] Setup completed."
echo
read -n 1 -s -r -p "Press any key to close..."
echo
