#!/bin/bash
# start.sh — backend + Vue SPA (web/)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API_URL="${API_URL:-http://127.0.0.1:8000}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

uvicorn backend.main:app --reload --host 127.0.0.1 --port "$BACKEND_PORT" --log-level info &
FASTAPI_PID=$!

cleanup() {
  echo "Shutting down services..."
  kill "$FASTAPI_PID" 2>/dev/null || true
  kill "$VITE_PID" 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

for i in $(seq 1 60); do
  if curl -sf "$API_URL/ping" >/dev/null 2>&1 || curl -sf "http://127.0.0.1:$BACKEND_PORT/ping" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

export VITE_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT"
(
  cd web
  npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"
) &
VITE_PID=$!

echo "Backend:  http://127.0.0.1:$BACKEND_PORT"
echo "Frontend: http://127.0.0.1:$FRONTEND_PORT"
wait
