#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/tmp/commerce-workstation-logs"
BACKEND_PORT="${BACKEND_PORT:-8789}"
FRONTEND_PORT="${FRONTEND_PORT:-8790}"
CLIPFORGE_PORT="${CLIPFORGE_PORT:-3010}"

mkdir -p "$LOG_DIR"

is_listening() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

start_backend() {
  if is_listening "$BACKEND_PORT"; then
    echo "Backend already listening on $BACKEND_PORT"
    return
  fi
  echo "Starting backend on $BACKEND_PORT"
  (cd "$ROOT_DIR" && nohup python3 backend/server.py --host 127.0.0.1 --port "$BACKEND_PORT" > "$LOG_DIR/backend.log" 2>&1 &)
}

start_frontend() {
  if is_listening "$FRONTEND_PORT"; then
    echo "Frontend static server already listening on $FRONTEND_PORT"
    return
  fi
  echo "Starting frontend static server on $FRONTEND_PORT"
  (cd "$ROOT_DIR" && nohup python3 -m http.server "$FRONTEND_PORT" > "$LOG_DIR/frontend.log" 2>&1 &)
}

start_clipforge() {
  if is_listening "$CLIPFORGE_PORT"; then
    echo "ClipForge already listening on $CLIPFORGE_PORT"
    return
  fi
  if [[ ! -d "$ROOT_DIR/.external/clipforge" ]]; then
    echo "Missing .external/clipforge. Clone ClipForge before starting the video generator."
    return
  fi
  echo "Starting ClipForge on $CLIPFORGE_PORT"
  (cd "$ROOT_DIR/.external/clipforge" && nohup pnpm exec next dev --webpack -p "$CLIPFORGE_PORT" > "$LOG_DIR/clipforge.log" 2>&1 &)
}

start_backend
start_frontend
start_clipforge

echo
echo "Commerce workstation:"
echo "  Frontend:  http://127.0.0.1:$FRONTEND_PORT/xhs-asset-generator-2.html"
echo "  Backend:   http://127.0.0.1:$BACKEND_PORT/api/health"
echo "  ClipForge: http://127.0.0.1:$CLIPFORGE_PORT/start"
echo "  Logs:      $LOG_DIR"
