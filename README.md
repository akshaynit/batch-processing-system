# Batch Processing System

A production-ready **asynchronous batch evaluation engine**. It reads an array of prompts from a
local file, returns a job id immediately, and runs the batch fully in the background: partitioning
prompts into chunks, fanning them out across a **bounded worker pool** that calls a live inference
endpoint, enforcing **rate-limit backpressure** (exponential back-off + jitter), isolating
per-row failures, and aggregating results into a downloadable report.

> The architecture and low-level design are documented in
> [`docs/Batch_Eval_Engine_Design.docx`](docs/Batch_Eval_Engine_Design.docx).

## API

| Method | Path | Description |
| --- | --- | --- |
| POST | `/jobs` | Ingest a batch file; returns a job id immediately (non-blocking). |
| GET | `/job/{id}/status` | Live progress: total / succeeded / failed / in-progress. |
| GET | `/job/{id}/download` | Final compiled results array (success + failure details). |

## Architecture (summary)

- **Ingestion** — streaming parse + validation; job id returned instantly.
- **Scatter / segmentation** — workers claim chunks from Postgres via `FOR UPDATE SKIP LOCKED`.
- **Backpressure** — concurrency semaphore + exponential back-off with full jitter.
- **Gather** — chunk results flushed to a pluggable storage backend (local now, DO Spaces later).

See the design document and `docs/diagrams/` for full diagrams.

## Project layout

```
app/
  api/            # FastAPI routers (controllers)
  core/           # config, exceptions, logging
  domain/         # enums + Pydantic models (contracts)
  interfaces/     # ABC ports: inference, storage, repositories, validation
  infrastructure/ # adapters: db (Postgres), inference (DO), storage (local/s3)
  services/       # JobService, BatchIngestor, validation pipeline
  engine/         # BatchEngine, Worker, ConcurrencyLimiter, RetryPolicy
  utils/          # token + cost estimation
workers/          # standalone worker-process entrypoint
scripts/          # sample-data generator, doc tooling
tests/            # unit + integration
```

## Quick start (Docker — recommended)

Brings up Postgres + the API server. The entrypoint applies DB migrations
automatically and the API resumes any interrupted jobs on startup.

```bash
cp .env.example .env          # set LLM_API_KEY (DigitalOcean model access key)
                              # and LLM_MODEL (e.g. mistral-3-14B)
docker compose up -d --build  # postgres + api on http://localhost:8000

# Exercise the API end-to-end (submit -> poll status -> download results):
scripts/api_demo.sh                         # uses sample_batch.json
scripts/api_demo.sh my_batch.json           # custom input
BASE_URL=http://host:8000 scripts/api_demo.sh
```

Call the endpoints directly:

```bash
curl -X POST localhost:8000/jobs -H 'content-type: application/json' \
     -d '{"input_path":"sample_batch.json"}'        # -> {"job_id": "..."}
curl localhost:8000/job/<job_id>/status
curl localhost:8000/job/<job_id>/download
```

## Quick start (local, no Docker)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d postgres                 # just the database
cp .env.example .env                          # set LLM_API_KEY / LLM_MODEL
alembic upgrade head                          # create tables
uvicorn app.main:app --reload                 # API on :8000
# optional: a standalone worker for a specific job (durable queue)
python workers/run_worker.py <job_id>
```

## Observability

Three pillars, all working out of the box (no external system required):

**1. Structured logs** — JSON, one object per line, written to stdout. Every line is
auto-tagged with correlation ids via contextvars, so you can trace a request or a
single inference call end-to-end:

```json
{"ts":"...","level":"INFO","logger":"app.engine.worker",
 "msg":"worker=... chunk=... processed=3 committed=3",
 "request_id":"4341c1...","job_id":"65cb33...","worker_id":"...-w0"}
```

Failed rows are logged at `ERROR` with the exact upstream message and attempt count.
Set `LOG_FORMAT=console` for human-readable local logs, `LOG_LEVEL` to tune verbosity.

**2. Metrics** — Prometheus text format at `GET /metrics` (just `curl` it; Prometheus
is optional). Key series:

| Metric | Meaning |
| --- | --- |
| `batch_http_requests_total{method,path,status}` | API traffic (low-cardinality path templates) |
| `batch_http_request_duration_seconds` | API latency histogram |
| `batch_jobs_submitted_total` / `batch_jobs_completed_total{state}` | Job throughput |
| `batch_ingest_items_total{result}` | Accepted vs rejected at ingestion |
| `batch_items_processed_total{status}` | Rows succeeded / failed |
| `batch_inference_requests_total{model,outcome}` | Inference success / retryable / permanent / unexpected |
| `batch_inference_duration_seconds{model}` | Per-call inference latency |
| `batch_inference_retries_total{model}` | Back-off retries triggered |
| `batch_inflight_requests` | Live concurrency (backpressure) gauge |
| `batch_chunks_claimed_total` | Work-queue claim rate |

**3. Error tracking (optional)** — set `SENTRY_DSN` and `pip install ".[observability]"`.
Unhandled API errors are captured automatically; isolated per-row and per-job failures
are reported explicitly with `job_id`/`external_id`/`model` tags. With no DSN it is a
complete no-op (the SDK is never imported).

### Optional dashboards (off by default)

```bash
docker compose --profile observability up -d
# Prometheus  -> http://localhost:9090  (scrapes api:8000/metrics every 15s)
# Grafana     -> http://localhost:3000  (Prometheus datasource pre-provisioned)
```

### Where to ship this in production

| Signal | Recommended (open-source) | Recommended (managed) |
| --- | --- | --- |
| Metrics | **Prometheus** (TSDB) + Grafana; VictoriaMetrics/Thanos for long retention | Grafana Cloud, Datadog |
| Logs | **Loki** (pairs with Grafana, cheap) or OpenSearch/ELK | Datadog, Better Stack |
| Traces | Tempo / Jaeger via OpenTelemetry | Grafana Cloud, Datadog |
| Errors | **Sentry** (self-hosted) | Sentry SaaS |

Note: metrics belong in a **time-series database** (Prometheus), not Postgres — Postgres
is for the durable job/work-queue state, not high-frequency telemetry. A common, cohesive
choice is the **Grafana stack (Prometheus + Loki + Tempo)** plus **Sentry** for errors.

## Development & tests

```bash
ruff check .
mypy app
pytest -m "not integration"            # unit tests (fast, no services)
pytest -m "integration and not live"   # DB integration tests (needs Postgres, no tokens)
pytest -m integration                  # + 1 real inference call (needs LLM_API_KEY in env)
```

Test layout:
- **unit** — pure logic (retry math, semaphore, validation); no I/O.
- **integration** (`tests/integration/`) — real Postgres: durable-queue claim/idempotency
  and a full mock-client pipeline (no token cost).
- **live** — a single real inference call with a minimal prompt; self-skips unless
  `LLM_API_KEY` is set.

## CI/CD (GitHub Actions)

`.github/workflows/ci.yml` runs on every push and PR:

1. **lint-and-unit** — `ruff` + unit tests with coverage.
2. **integration** — spins up a Postgres service, applies migrations, runs the DB
   integration suite, and makes **exactly one** real inference call **only if** the
   `LLM_API_KEY` secret is configured (otherwise that one test self-skips). Token usage
   per run is therefore at most a single tiny completion.
3. **docker-build** — builds the production image to keep the `Dockerfile` honest.

To enable the live call in CI, add repository secrets:
`LLM_API_KEY` (required) and optionally `LLM_MODEL` (defaults to `mistral-3-14B`).

## Regenerating the design document

```bash
pip install ".[docs]"
python scripts/render_diagrams.py   # docs/diagrams/*.mmd -> docs/assets/*.png
python scripts/build_doc.py         # -> docs/Batch_Eval_Engine_Design.docx
```
