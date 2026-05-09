#!/bin/bash
set -u

cd "$(dirname "$0")"

echo "======================================"
echo "Quant Platform - Launch Streamlit App"
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

if command -v streamlit >/dev/null 2>&1; then
  streamlit run app.py
else
  echo "[INFO] streamlit command not in PATH, trying: $PY_BIN -m streamlit"
  "$PY_BIN" -m streamlit run app.py
fi

status=$?
if [ $status -ne 0 ]; then
  echo
  echo "[ERROR] Failed to run Streamlit app (status $status)."
fi

echo
read -n 1 -s -r -p "Press any key to close..."
echo
