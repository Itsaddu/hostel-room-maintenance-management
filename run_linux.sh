#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [[ ! -x "$VENV_PYTHON" ]] || ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
  if ! python3 -m ensurepip --version >/dev/null 2>&1; then
    PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    echo "Python venv support is missing. Install it, then rerun this script:"
    echo "  sudo apt update && sudo apt install python${PYTHON_VERSION}-venv"
    exit 1
  fi
  python3 -m venv --clear "$VENV_DIR"
fi

REQUIREMENTS_HASH="$(sha256sum requirements.txt | cut -d ' ' -f 1)"
HASH_FILE="$VENV_DIR/.requirements.sha256"
if [[ ! -f "$HASH_FILE" ]] || [[ "$(cat "$HASH_FILE")" != "$REQUIREMENTS_HASH" ]] || ! "$VENV_PYTHON" -c 'import streamlit, pandas' >/dev/null 2>&1; then
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV_PYTHON" -m pip install -r requirements.txt
  printf '%s\n' "$REQUIREMENTS_HASH" > "$HASH_FILE"
fi

exec "$VENV_PYTHON" -m streamlit run app.py
