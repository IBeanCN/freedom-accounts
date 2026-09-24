#!/usr/bin/env bash
# freedom-accounts launcher
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

stop_existing_processes() {
  local pid
  local pids=()
  local candidates

  # Exact backend module plus this repo's Vite binary avoid killing unrelated
  # Node/Python services that happen to listen on the same ports.
  candidates="$(pgrep -f 'uvicorn app\.main:app' || true)"
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    pids+=("$pid")
  done <<< "$candidates"

  candidates="$(pgrep -f "$ROOT/frontend/node_modules/(\\.bin/vite|vite/bin/vite\\.js)" || true)"
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    pids+=("$pid")
  done <<< "$candidates"

  if [ "${#pids[@]}" -eq 0 ]; then
    return
  fi

  echo "[*] stopping existing freedom-accounts processes..."
  for pid in "${pids[@]}"; do
    printf '    PID %s: %s\n' "$pid" "$(ps -o command= -p "$pid" 2>/dev/null || true)"
    kill "$pid" 2>/dev/null || true
  done

  local remaining=()
  for _ in {1..20}; do
    remaining=()
    for pid in "${pids[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        remaining+=("$pid")
      fi
    done
    [ "${#remaining[@]}" -eq 0 ] && break
    sleep 0.2
  done

  if [ "${#remaining[@]}" -gt 0 ]; then
    echo "[*] force stopping unresponsive processes..."
    kill -9 "${remaining[@]}" 2>/dev/null || true
  fi
}

stop_existing_processes

mode="${1:---dev}"

case "$mode" in
  -d|--dev)
    mode="dev"
    ;;
  -p|--prod)
    mode="prod"
    ;;
  -h|--help)
    echo "Usage: ./run.sh [--dev|--prod]"
    echo "  --dev  Start FastAPI and the Vite dev server for frontend development (default)."
    echo "  --prod Build frontend/dist and serve it from FastAPI."
    exit 0
    ;;
  --prod)
    ;;
  *)
    echo "Unknown option: $mode" >&2
    echo "Use --help for supported modes." >&2
    exit 2
    ;;
esac

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required for the frontend." >&2
  exit 1
fi

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

if [ "$mode" = "dev" ]; then
  backend_port="${FA_PORT:-8000}"
  frontend_port="${FRONTEND_PORT:-5173}"
  export FA_PORT="$backend_port"
  backend_pid=""

  cleanup() {
    trap - EXIT INT TERM
    if [ -n "$backend_pid" ]; then
      kill "$backend_pid" 2>/dev/null || true
      wait "$backend_pid" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT INT TERM

  echo "[*] starting backend at http://127.0.0.1:$backend_port..."
  python -m uvicorn app.main:app --host "${FA_HOST:-127.0.0.1}" --port "$backend_port" --log-level debug &
  backend_pid=$!

  echo "[*] starting frontend at http://127.0.0.1:$frontend_port..."
  (
    cd frontend
    if [ ! -d node_modules ]; then
      npm ci --no-audit --no-fund
    fi
    npm run dev -- --host 127.0.0.1 --port "$frontend_port" --strictPort
  )
else
  echo "[*] building frontend..."
  (
    cd frontend
    if [ ! -d node_modules ]; then
      npm ci --no-audit --no-fund
    fi
    npm run build
  )

  echo "[*] starting freedom-accounts at http://127.0.0.1:${FA_PORT:-10008} (admin / admin123)"
  exec python -m uvicorn app.main:app --host "${FA_HOST:-127.0.0.1}" --port "${FA_PORT:-10008}" --log-level debug
fi
