#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
cd "$ROOT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "错误：找不到 $PYTHON_BIN，请安装 Python 3.10 或更高版本。" >&2
  exit 1
fi

mkdir -p results
"$PYTHON_BIN" run_demo.py --scenario baseline --output results/baseline.json
"$PYTHON_BIN" run_demo.py --scenario compare --output results/compare.json
"$PYTHON_BIN" run_demo.py --scenario deadlock --output results/deadlock.json
echo "实验完成，结果位于 $ROOT_DIR/results/"
