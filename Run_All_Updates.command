#!/bin/bash
set -u

cd "$(dirname "$0")"

echo "======================================"
echo "Quant Platform - Update Pipeline Start"
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

echo "[1/4] Running python -m command.update_data ..."
"$PY_BIN" -m command.update_data
if [ $? -ne 0 ]; then
  echo "[ERROR] command.update_data failed."
  echo
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit 1
fi

echo
echo "[2/4] Refreshing Risk-Adjusted Growth bank JSON feeds if local scrape exists ..."
if [ -d "/Users/macos/Desktop/bctc-scrape/Statistics/json" ] && [ -d "/Users/macos/Desktop/bctc-scrape/BCTC/json" ]; then
  "$PY_BIN" -m command.update_risk_adjusted_growth_statistics
  if [ $? -ne 0 ]; then
    echo "[ERROR] command.update_risk_adjusted_growth_statistics failed."
    echo
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit 1
  fi
else
  echo "[SKIP] Local scrape folders not found: /Users/macos/Desktop/bctc-scrape/Statistics/json and /Users/macos/Desktop/bctc-scrape/BCTC/json"
fi

echo
echo "[3/4] Running python -m command.update_pvgo_valuation ..."
"$PY_BIN" -m command.update_pvgo_valuation
if [ $? -ne 0 ]; then
  echo "[ERROR] command.update_pvgo_valuation failed."
  echo
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit 1
fi

echo
echo "[4/4] Running python -m command.update_vnibor ..."
"$PY_BIN" -m command.update_vnibor
if [ $? -ne 0 ]; then
  echo "[ERROR] command.update_vnibor failed."
  echo
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit 1
fi

echo
echo "[DONE] All update scripts finished."
echo
read -n 1 -s -r -p "Press any key to close..."
echo
