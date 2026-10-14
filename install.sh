#!/usr/bin/env bash
# One-time setup for PYQ Analyzer (Linux / macOS / Git Bash on Windows).
# Installs uv, creates backend/.venv, installs backend + frontend packages, pulls the local OCR model.
# Safe to re-run.
#
#   ./install.sh                 # everything
#   ./install.sh --skip-models   # no Ollama model download
#   ./install.sh --with-v1-models --test
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

# Models (keep in sync with backend/app/config.py)
OCR_MODEL="hf.co/sahilchachra/Unlimited-OCR-GGUF:Q4_K_M"
V1_MODELS=("huihui_ai/gemma-4-abliterated:e4b" "moondream:latest")

SKIP_MODELS=0; WITH_V1=0; RUN_TESTS=0
for a in "$@"; do
  case "$a" in
    --skip-models) SKIP_MODELS=1 ;;
    --with-v1-models) WITH_V1=1 ;;
    --test) RUN_TESTS=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32mok\033[0m  %s\n' "$1"; }
warn() { printf '    \033[33m!!\033[0m  %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

OS="$(uname -s)"
pkg_hint() {  # how to install a missing system tool
  case "$OS" in
    Darwin) echo "brew install $1" ;;
    Linux) echo "sudo apt install $1   (or your distro's package manager)" ;;
    *) echo "winget install $2" ;;
  esac
}

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# -- 1. tools --
step "Checking tools"
if ! have uv; then
  echo "    installing uv (Python manager) from astral.sh..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
have uv && ok "$(uv --version)" || { echo "uv could not be installed" >&2; exit 1; }

if ! have node; then
  echo "Node.js (LTS) is required: $(pkg_hint nodejs OpenJS.NodeJS.LTS)  or https://nodejs.org" >&2
  exit 1
fi
ok "node $(node --version)"

if ! have ollama; then
  if [ "$OS" = "Linux" ]; then
    echo "    installing Ollama (official script)..."
    curl -fsSL https://ollama.com/install.sh | sh
  else
    echo "Ollama is required for local OCR: https://ollama.com/download  ($(pkg_hint ollama Ollama.Ollama))" >&2
    exit 1
  fi
fi
ok "ollama"

have ffmpeg && ok "ffmpeg (lesson videos)" || warn "ffmpeg missing - lesson MP4 export unavailable: $(pkg_hint ffmpeg Gyan.FFmpeg)"
if have agy; then
  ok "agy CLI (web search + repair of flagged questions)"
else
  warn "agy CLI not found: the app works local-only (uploads, DSpace, local OCR);"
  warn "web search and repair of hard scans need the Antigravity 'agy' CLI on PATH, signed in."
fi
case "$OS" in
  MINGW*|MSYS*|CYGWIN*|Darwin) ;;
  *) have espeak-ng && ok "espeak-ng (lesson narration)" || warn "espeak-ng missing - lesson MP4 export needs it: $(pkg_hint espeak-ng espeak-ng)" ;;
esac

# -- 2. backend --
step "Backend: Python 3.12 virtual environment + packages"
if [ -x "$BACKEND/.venv/bin/python" ]; then PY="$BACKEND/.venv/bin/python"
elif [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then PY="$BACKEND/.venv/Scripts/python.exe"
else
  uv venv "$BACKEND/.venv" --python 3.12
  if [ -x "$BACKEND/.venv/bin/python" ]; then PY="$BACKEND/.venv/bin/python"; else PY="$BACKEND/.venv/Scripts/python.exe"; fi
fi
uv pip install --python "$PY" -r "$BACKEND/pyproject.toml" --extra dev
"$PY" -c "import fastapi, sqlalchemy, pypdfium2, matplotlib" && ok "backend packages import"
if [ ! -f "$BACKEND/.env" ] && [ -f "$BACKEND/.env.example" ]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  ok "created backend/.env from .env.example (all settings optional)"
fi

# -- 3. frontend --
step "Frontend: npm packages"
( cd "$FRONTEND" && if [ -f package-lock.json ]; then npm ci --no-fund --no-audit; else npm install --no-fund --no-audit; fi )
ok "frontend packages"

# -- 4. models --
if [ "$SKIP_MODELS" = 1 ]; then
  step "Skipping model download (--skip-models)"
else
  step "Local OCR model (Ollama)"
  if ! port_open 11434; then
    echo "    starting ollama serve..."
    nohup ollama serve >/dev/null 2>&1 &
    for _ in $(seq 1 30); do port_open 11434 && break; sleep 1; done
  fi
  port_open 11434 || { echo "Ollama is not answering on port 11434" >&2; exit 1; }
  models=("$OCR_MODEL")
  [ "$WITH_V1" = 1 ] && models+=("${V1_MODELS[@]}")
  for m in "${models[@]}"; do
    echo "    pulling $m (first time can take a while)..."
    ollama pull "$m"
    ok "$m"
  done
fi

# -- 5. check --
if [ "$RUN_TESTS" = 1 ]; then
  step "Backend tests"
  ( cd "$BACKEND" && "$PY" -m pytest -q )
fi

step "Done"
echo "    Start the app with:  ./start.sh   (database is created / migrated on first start)"
