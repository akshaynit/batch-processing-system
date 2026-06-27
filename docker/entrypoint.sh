#!/usr/bin/env bash
# Container entrypoint: applies DB migrations, then runs the requested process.
#
#   entrypoint.sh api            -> uvicorn API server (default)
#   entrypoint.sh worker <id>    -> standalone worker for a job id
#   entrypoint.sh <cmd...>       -> exec arbitrary command
set -euo pipefail

run_migrations() {
  echo "[entrypoint] applying database migrations..."
  for attempt in $(seq 1 10); do
    if alembic upgrade head; then
      echo "[entrypoint] migrations applied."
      return 0
    fi
    echo "[entrypoint] migration attempt ${attempt} failed; retrying in 3s..."
    sleep 3
  done
  echo "[entrypoint] migrations failed after retries." >&2
  exit 1
}

cmd="${1:-api}"
case "$cmd" in
  api)
    run_migrations
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    shift
    exec python workers/run_worker.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
