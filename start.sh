#!/usr/bin/env bash
# Start StegoLab (API on :8000, web app on :5173). Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
[ -x "$ROOT/backend/.venv/bin/python" ] || { echo "Run ./setup.sh first."; exit 1; }

(cd "$ROOT/backend" && exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT INT TERM
echo "API      http://127.0.0.1:8000/api/health  (docs: /docs)"
echo "Web app  http://localhost:5173"
cd "$ROOT/frontend" && npm run dev
