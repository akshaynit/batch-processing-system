#!/usr/bin/env bash
# End-to-end API client: submit a batch, poll status, download results.
#
# Usage:
#   scripts/api_demo.sh [input_path] [base_url]
#
# Env overrides:
#   BASE_URL   (default: http://localhost:8000)
#   INPUT      (default: sample_batch.json)
#   INTERVAL   poll interval seconds (default: 1)
#   TIMEOUT    max seconds to wait (default: 120)
set -euo pipefail

BASE_URL="${2:-${BASE_URL:-http://localhost:8000}}"
INPUT="${1:-${INPUT:-sample_batch.json}}"
INTERVAL="${INTERVAL:-1}"
TIMEOUT="${TIMEOUT:-120}"

say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

say "Health check ($BASE_URL/health)"
curl -fsS "$BASE_URL/health"; echo

say "Submitting job (input=$INPUT)"
SUBMIT_RESP="$(curl -fsS -X POST "$BASE_URL/jobs" \
  -H 'content-type: application/json' \
  -d "{\"input_path\": \"$INPUT\"}")"
echo "$SUBMIT_RESP"
JOB_ID="$(printf '%s' "$SUBMIT_RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["job_id"])')"
echo "job_id = $JOB_ID"

say "Polling status (every ${INTERVAL}s, timeout ${TIMEOUT}s)"
elapsed=0
while :; do
  STATUS_JSON="$(curl -fsS "$BASE_URL/job/$JOB_ID/status")"
  STATE="$(printf '%s' "$STATUS_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["state"])')"
  printf '%s\n' "$STATUS_JSON" | python3 -c '
import sys, json
s = json.load(sys.stdin)
print("  state=%s total=%s pending=%s in_progress=%s succeeded=%s failed=%s" % (
    s["state"], s["total"], s["pending"], s["in_progress"], s["succeeded"], s["failed"]))'
  case "$STATE" in
    COMPLETED|FAILED) break ;;
  esac
  if [ "$elapsed" -ge "$TIMEOUT" ]; then
    echo "  timed out after ${TIMEOUT}s" >&2; exit 1
  fi
  sleep "$INTERVAL"; elapsed=$((elapsed + INTERVAL))
done

say "Downloading results ($BASE_URL/job/$JOB_ID/download)"
curl -fsS "$BASE_URL/job/$JOB_ID/download" | python3 -c '
import sys, json
data = json.load(sys.stdin)
ok = sum(1 for r in data if r["status"] == "SUCCEEDED")
print("  returned %d records  (%d succeeded, %d failed)\n" % (len(data), ok, len(data) - ok))
for r in data:
    if r["status"] == "SUCCEEDED":
        print("  [%s] OK (%sms): %r" % (r["external_id"], r.get("latency_ms"), r.get("response")))
    else:
        print("  [%s] FAILED: %s" % (r["external_id"], r.get("error")))'

say "Done. job_id=$JOB_ID"
