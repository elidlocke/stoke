#!/usr/bin/env bash
# Starts Stoke locally: Postgres, migrations, the API and the frontend. Ctrl+C stops the API and
# frontend; Postgres keeps running (stop it with `docker compose stop`).
set -euo pipefail
cd "$(dirname "$0")"

if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running. Open Docker Desktop, then run this again." >&2
  exit 1
fi

echo "→ Starting Postgres"
docker compose up -d --wait db

echo "→ Running migrations"
(cd backend && uv run alembic upgrade head)

if [ ! -d frontend/node_modules ] || [ frontend/package-lock.json -nt frontend/node_modules ]; then
  echo "→ Installing frontend dependencies"
  (cd frontend && npm install)
fi

# Stop both servers on Ctrl+C.
trap 'kill 0' EXIT

echo "→ Starting the API on http://127.0.0.1:8000"
(cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --reload) &

echo "→ Starting the frontend on http://localhost:5173"
(cd frontend && npm run dev) &

wait
