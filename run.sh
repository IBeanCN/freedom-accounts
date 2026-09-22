#!/usr/bin/env bash
# freedom-accounts launcher
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "[*] creating venv..."
  python3 -m venv .venv
fi
source .venv/bin/activate

if [ ! -f .venv/.deps_installed ] || [ requirements.txt -nt .venv/.deps_installed ]; then
  echo "[*] installing dependencies..."
  pip install -q -r requirements.txt
  touch .venv/.deps_installed
fi

echo "[*] starting freedom-accounts at http://127.0.0.1:8000 (admin / admin123)"
exec python -m uvicorn app.main:app --host "${FA_HOST:-127.0.0.1}" --port "${FA_PORT:-8000}"
