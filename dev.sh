#!/usr/bin/env bash
# Starts Stoke locally: Postgres, migrations, the API and the frontend. Ctrl+C stops the API and
# frontend; Postgres keeps running (stop it with `docker compose stop`).
set -euo pipefail
cd "$(dirname "$0")"

if ! docker info >/dev/null 2>&1; then
  echo "Docker isn't running. Open Docker Desktop, then run this again." >&2
  exit 1
fi

# Stops an earlier API or frontend from this repo still holding a port (e.g. from a closed terminal), so the
# new one doesn't fail to start while the old one keeps answering with stale code and settings. Anything else
# on the port is left alone.
free_port() {
  local port=$1 name=$2 pids pid cmd cwd parent parents=""
  pids=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN || true)
  [ -z "$pids" ] && return 0
  for pid in $pids; do
    cmd=$(ps -o command= -p "$pid" || true)
    # uvicorn --reload serves from a worker whose command line doesn't name the repo; its directory does.
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)
    if [[ "$cmd" != *"$PWD"* && "$cwd" != "$PWD"* ]]; then
      echo "Port $port is in use by another program (pid $pid: $cmd). Stop it, then run this again." >&2
      exit 1
    fi
    # Its --reload parent too, or it would start another worker on the next file change.
    parent=$(ps -o ppid= -p "$pid" | tr -d ' ')
    [[ -n "$parent" && "$(ps -o command= -p "$parent" || true)" == *"$PWD"* ]] && parents="$parents $parent"
  done
  echo "→ Stopping an earlier $name on port $port"
  kill $pids $parents 2>/dev/null || true
  for _ in {1..50}; do
    lsof -nP -tiTCP:"$port" -sTCP:LISTEN >/dev/null || return 0
    sleep 0.1
  done
  kill -9 $(lsof -nP -tiTCP:"$port" -sTCP:LISTEN) 2>/dev/null || true
}

free_port 8000 API
free_port 5173 frontend

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

echo "→ Starting the frontend on https://localhost:5173"
# --strictPort: fail rather than move to another port, which wouldn't match Auth0's and Google's redirect URLs.
(cd frontend && npm run dev -- --strictPort) &

wait
