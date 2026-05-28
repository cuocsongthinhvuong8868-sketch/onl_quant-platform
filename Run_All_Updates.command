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

echo "[1/3] Running python -m command.update_data ..."
"$PY_BIN" -m command.update_data
if [ $? -ne 0 ]; then
  echo "[ERROR] command.update_data failed."
  echo
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit 1
fi

echo
echo "[2/3] Running python -m command.update_bank_fundamentals ..."
"$PY_BIN" -m command.update_bank_fundamentals
if [ $? -ne 0 ]; then
  echo "[ERROR] command.update_bank_fundamentals failed."
  echo
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit 1
fi

echo
echo "[3/3] Running python -m command.update_vnibor ..."
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
