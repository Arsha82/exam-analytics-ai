#!/usr/bin/env bash
# Starts PYQ Analyzer (Linux / macOS / Git Bash): Ollama if needed, backend API, web UI.
#
#   ./start.sh              # start (background) and open the browser
#   ./start.sh --stop       # stop backend + frontend
#   ./start.sh --port 8020 --no-browser
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
RUN="$ROOT/.run"
PIDS="$RUN/pids.txt"
PORT=8010; OPEN=1; STOP=0
UI="http://localhost:5173"

while [ $# -gt 0 ]; do
  case "$1" in
    --stop) STOP=1 ;;
    --no-browser) OPEN=0 ;;
    --port) PORT="$2"; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
wait_url() { for _ in $(seq 1 "$2"); do curl -fsS -o /dev/null "$1" 2>/dev/null && return 0; sleep 1; done; return 1; }
is_windows() { case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) return 0 ;; *) return 1 ;; esac; }

stop_started() {
  [ -f "$PIDS" ] || { echo "Nothing to stop."; return 0; }
  while read -r pid; do
    [ -n "$pid" ] || continue
    if is_windows; then taskkill //PID "$pid" //T //F >/dev/null 2>&1 || true
    else pkill -TERM -P "$pid" 2>/dev/null || true; kill "$pid" 2>/dev/null || true; fi
  done < "$PIDS"
  rm -f "$PIDS"
  echo "Stopped PYQ Analyzer (backend + frontend). Ollama is left running."
}

if [ "$STOP" = 1 ]; then stop_started; exit 0; fi

if [ -x "$BACKEND/.venv/bin/python" ]; then PY="$BACKEND/.venv/bin/python"
elif [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then PY="$BACKEND/.venv/Scripts/python.exe"
else echo "backend/.venv not found - run ./install.sh first" >&2; exit 1; fi
[ -d "$FRONTEND/node_modules" ] || { echo "frontend/node_modules not found - run ./install.sh first" >&2; exit 1; }

mkdir -p "$RUN"
[ -f "$PIDS" ] && stop_started
: > "$PIDS"

if port_open 11434; then echo "ollama    already running"
elif command -v ollama >/dev/null 2>&1; then nohup ollama serve >/dev/null 2>&1 & echo "ollama    starting..."
else echo "ollama    not installed - scanned papers cannot be read locally (run ./install.sh)"; fi

if port_open "$PORT"; then echo "Port $PORT is already in use (use --port <other>)." >&2; exit 1; fi
( cd "$BACKEND" && nohup "$PY" -m uvicorn app.main:app --port "$PORT" >"$RUN/backend.log" 2>&1 & echo $! >> "$PIDS" )
echo "backend   starting on http://127.0.0.1:$PORT (log: .run/backend.log)"
( cd "$FRONTEND" && VITE_API_PORT="$PORT" nohup npm run dev >"$RUN/frontend.log" 2>&1 & echo $! >> "$PIDS" )

if ! wait_url "http://127.0.0.1:$PORT/api/system/status" 90; then
  echo "backend did not come up - last lines of .run/backend.log:" >&2; tail -n 20 "$RUN/backend.log" >&2
  stop_started; exit 1
fi
echo "backend   ready"
if ! wait_url "$UI" 60; then echo "frontend did not come up - see .run/frontend.log" >&2; stop_started; exit 1; fi
echo "frontend  ready: $UI"

if [ "$OPEN" = 1 ]; then
  if is_windows; then start "" "$UI" 2>/dev/null || cmd //c start "" "$UI"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$UI" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then open "$UI"; fi
fi
echo
echo "Running in the background. Stop with:  ./start.sh --stop"
