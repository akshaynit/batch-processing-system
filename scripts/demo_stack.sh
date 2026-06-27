#!/usr/bin/env bash
# One-shot demo: build + run the Docker stack (Postgres + uvicorn API with
# auto-migrations), wait for health, drive the API end-to-end (submit -> poll
# -> download), then gather and print the API container logs.
#
# Usage:
#   scripts/demo_stack.sh [input_path]
#
# Env overrides:
#   BASE_URL  (default: http://localhost:8000)
#   INPUT     (default: sample_batch.json)
#   INTERVAL  status poll interval seconds (default: 2)
#   TIMEOUT   max seconds to wait per phase (default: 180)
#   LOG_LINES tail of API logs to show at the end (default: 150)
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

BASE_URL="${BASE_URL:-http://localhost:8000}"
INPUT="${1:-${INPUT:-sample_batch.json}}"
INTERVAL="${INTERVAL:-2}"
TIMEOUT="${TIMEOUT:-180}"
LOG_LINES="${LOG_LINES:-150}"

# docker compose v2 (plugin) or v1 (standalone)
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
PY="$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )"

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m!! %s\033[0m\n' "$*" >&2; }

# A relative INPUT must exist BEFORE compose up, because it is bind-mounted into
# the container (a missing path would be mounted as an empty directory).
if [ ! -f "$INPUT" ] && [ "$INPUT" = "sample_batch.json" ]; then
  say "Generating sample input ($INPUT)"
  "$PY" scripts/generate_sample_batch.py || python3 scripts/generate_sample_batch.py
fi

say "Building images"
$DC build

say "Starting postgres + api (DB migrations run in the api entrypoint)"
$DC up -d postgres api

say "Waiting for API health at $BASE_URL/health"
deadline=$((SECONDS + TIMEOUT))
until curl -fsS "$BASE_URL/health" >/dev/null 2>&1; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    fail "API did not become healthy in ${TIMEOUT}s; dumping logs:"
    $DC logs api || true
    exit 1
  fi
  sleep 2
done
curl -fsS "$BASE_URL/health"; echo

say "Prompts in this batch ($INPUT)"
"$PY" - "$INPUT" <<'PY' || echo "  (could not read $INPUT)"
import json, sys
with open(sys.argv[1]) as fh:
    data = json.load(fh)
print("  %d prompt(s):" % len(data))
for i, r in enumerate(data, 1):
    p = (r.get("prompt") or "").replace("\n", " ")
    if len(p) > 100:
        p = p[:100] + "..."
    print("  %2d. [%s] %s" % (i, r.get("id", "?"), p))
PY

say "Submitting job (input=$INPUT)"
SUBMIT_RESP="$(curl -fsS -X POST "$BASE_URL/jobs" \
  -H 'content-type: application/json' \
  -d "{\"input_path\": \"$INPUT\"}")"
echo "$SUBMIT_RESP"
JOB_ID="$(printf '%s' "$SUBMIT_RESP" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["job_id"])')"
echo "job_id = $JOB_ID"

say "Polling status (every ${INTERVAL}s, timeout ${TIMEOUT}s)"
elapsed=0
while :; do
  STATUS_JSON="$(curl -fsS "$BASE_URL/job/$JOB_ID/status")"
  STATE="$(printf '%s' "$STATUS_JSON" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["state"])')"
  printf '%s\n' "$STATUS_JSON" | "$PY" -c '
import sys, json
s = json.load(sys.stdin)
print("  state=%s total=%s pending=%s in_progress=%s succeeded=%s failed=%s" % (
    s["state"], s["total"], s["pending"], s["in_progress"], s["succeeded"], s["failed"]))'
  case "$STATE" in COMPLETED|FAILED) break ;; esac
  if [ "$elapsed" -ge "$TIMEOUT" ]; then fail "polling timed out after ${TIMEOUT}s"; break; fi
  sleep "$INTERVAL"; elapsed=$((elapsed + INTERVAL))
done

say "Downloading results ($BASE_URL/job/$JOB_ID/download)"
curl -fsS "$BASE_URL/job/$JOB_ID/download" | "$PY" -c '
import sys, json
data = json.load(sys.stdin)
ok = sum(1 for r in data if r["status"] == "SUCCEEDED")
print("  returned %d records  (%d succeeded, %d failed)" % (len(data), ok, len(data) - ok))
for r in data[:5]:
    payload = r.get("response") if r["status"] == "SUCCEEDED" else r.get("error")
    print("  [%s] %s: %s" % (r["external_id"], r["status"], repr(payload)[:140]))'

say "API container logs (last ${LOG_LINES} lines)"
$DC logs --tail "$LOG_LINES" api

say "Log file location"
LOG_FILE_ENV="$(grep -E '^LOG_FILE=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r')"
if [ -n "${LOG_FILE_ENV:-}" ]; then
  # Map the in-container path (/app/data/...) to the host bind-mount (./data/...).
  HOST_LOG="$LOG_FILE_ENV"
  case "$HOST_LOG" in
    /app/data/*) HOST_LOG="./data/${HOST_LOG#/app/data/}" ;;
  esac
  echo "  in container : $LOG_FILE_ENV"
  echo "  on host      : $HOST_LOG"
  if [ -f "$HOST_LOG" ]; then
    echo "  size         : $(wc -c < "$HOST_LOG" | tr -d ' ') bytes"
    echo "  follow with  : tail -f $HOST_LOG"
  else
    echo "  (host file not present yet — it appears once the container writes a log line)"
  fi
else
  echo "  LOG_FILE is not set in .env -> logs go to stdout only."
  echo "  view with    : $DC logs -f api"
fi

say "Done. job_id=$JOB_ID   (stop the stack with: $DC down)"
