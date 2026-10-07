#!/usr/bin/env bash
# StegoLab one-time setup (Linux / macOS).
#   ./setup.sh          # auto-detects an NVIDIA GPU
#   ./setup.sh --cpu    # force CPU-only PyTorch
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

PY=""
for candidate in python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || { echo "Python 3.11+ is required (3.12 recommended)"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "Node.js 20+ is required"; exit 1; }

step "Creating Python virtual environment (backend/.venv)"
cd "$ROOT/backend"
[ -d .venv ] || "$PY" -m venv .venv
VPY="$ROOT/backend/.venv/bin/python"
"$VPY" -m pip install --upgrade pip --quiet

INDEX="https://download.pytorch.org/whl/cpu"
if [ "${1:-}" != "--cpu" ] && command -v nvidia-smi >/dev/null 2>&1; then INDEX="https://download.pytorch.org/whl/cu128"; fi
if [ "$(uname)" = "Darwin" ]; then INDEX=""; fi   # macOS wheels come from PyPI (MPS/CPU)
step "Installing PyTorch (${INDEX:-PyPI default})"
if [ -n "$INDEX" ]; then "$VPY" -m pip install torch torchvision --index-url "$INDEX" --quiet; else "$VPY" -m pip install torch torchvision --quiet; fi
step "Installing backend dependencies"
"$VPY" -m pip install -r requirements-dev.txt --quiet

step "Generating backend/.env with random secrets (kept if it already exists)"
"$VPY" "$ROOT/scripts/init_env.py"

step "Creating the database, admin account, model registry and research results"
"$VPY" -m alembic upgrade head
"$VPY" -m app.cli bootstrap-admin
"$VPY" -m app.cli sync-models
"$VPY" -m app.cli import-experiments

step "Installing frontend dependencies"
cd "$ROOT/frontend" && npm install --no-fund --no-audit

printf '\n\033[32mSetup complete.\033[0m Start with ./start.sh\n'
echo "Admin login: BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD in backend/.env"
