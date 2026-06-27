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

### Run a 1000-prompt batch

The input is a JSON **array** of `{ "id", "prompt" }` objects:

```json
[
  { "id": "prompt-0001", "prompt": "Explain photosynthesis in one sentence." },
  { "id": "prompt-0002", "prompt": "Summarize the key idea behind recursion." }
]
```

Generate a 1000-item template and run the whole pipeline end-to-end:

```bash
# 1) Generate the input template (1000 items -> ./sample_batch.json, bind-mounted into the API)
python scripts/generate_sample_batch.py 1000 sample_batch.json

# 2) Submit -> poll -> download. Raise the client timeout for a larger batch.
TIMEOUT=900 scripts/api_demo.sh sample_batch.json
```

> 💰 **Cost note:** 1000 prompts = ~1000 live inference calls. For free, repeatable
> testing of the *plumbing* at this size, use the mock client instead (no tokens):
> `python scripts/smoke_e2e.py sample_batch.json`. Tune throughput with the knobs in
> [Scaling & resource thresholds](#scaling--resource-thresholds).

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

## Scaling & resource thresholds

The full architectural/memory analysis lives in
[`docs/Batch_Eval_Engine_Design.docx`](docs/Batch_Eval_Engine_Design.docx); this is the
operational summary.

### The three tuning knobs (env)

| Knob | Default | What it controls |
| --- | --- | --- |
| `WORKER_POOL_SIZE` | 4 | Worker coroutines that claim chunks and orchestrate flush/heartbeat. |
| `MAX_CONCURRENCY` | 10 | **Hard cap on in-flight inference calls** (the backpressure semaphore, shared across all workers). This is the real throughput dial. |
| `CHUNK_SIZE` | 50 | Rows claimed per DB round-trip and processed together before a checkpoint flush. |

Supporting knobs: `RETRY_MAX_ATTEMPTS`, `RETRY_BASE/FACTOR/CAP` (back-off), `LEASE_TTL_SECONDS`, `HEARTBEAT_SECONDS`.

### Why it does not OOM at 500k items

Memory is **bounded and independent of total batch size N**:

- **Ingestion streams** the file with `ijson` and inserts in batches of 500 — the input is never fully loaded. Peak ≈ one insert batch.
- **Processing working set** is `WORKER_POOL_SIZE × CHUNK_SIZE` rows resident at once (defaults: 4 × 50 = **200 rows**). Each chunk's results are flushed to storage and released before the next claim — so 1k and 500k items have the *same* in-flight footprint (a few MB; even 16×500 is only tens of MB).
- **Download streams** results from disk chunk-by-chunk (`StreamingResponse`), O(1) memory.
- The only O(N) state is the `prompt_items` rows in **Postgres** (on disk, where it belongs) and the per-chunk result files on disk/Spaces.

### Throughput, ceilings & bottlenecks

Throughput ≈ `MAX_CONCURRENCY / avg_latency`, capped by the provider's rate limit.

| Batch | MAX_CONCURRENCY | ~avg 1s latency | Wall-clock (rough) |
| --- | --- | --- | --- |
| 1,000 | 10 | 10 req/s | ~100 s |
| 1,000 | 50 | 50 req/s | ~20 s |
| 500,000 | 50 (1 process) | 50 req/s | ~2.8 h |
| 500,000 | 200 (4 worker replicas × 50) | 200 req/s | ~42 min |

Bottleneck order as you scale: **(1) provider rate limit / latency → (2) `MAX_CONCURRENCY` → (3) DB claim contention (only with very small chunks) → (4) storage write throughput.** App RAM is never the limit.

`CHUNK_SIZE` trade-off: larger chunks mean fewer DB claims (less overhead) but more memory per worker, coarser flush granularity, and more reprocessing if a worker dies mid-chunk (≤ `CHUNK_SIZE` rows redone). Heartbeats renew the lease every `HEARTBEAT_SECONDS`, so a chunk is **not** bounded by `LEASE_TTL_SECONDS` — lease expiry happens only when a worker actually dies, after which the chunk is safely reclaimed.

### Recommended settings by scale

| Scale | Topology | WORKER_POOL_SIZE | MAX_CONCURRENCY | CHUNK_SIZE |
| --- | --- | --- | --- | --- |
| ≤ 1k (dev/test) | single process | 4 | 10 | 50 |
| 10k–50k | single process | 4–8 | 20–50 | 50–100 |
| 100k–500k+ | **multiple worker replicas** + managed Postgres | 4–8 / replica | 20–50 / replica | 100 |

Always keep `MAX_CONCURRENCY` at or below the provider's rate limit to avoid burning retries.

### Horizontal scaling

The work queue is durable and claims are atomic (`FOR UPDATE SKIP LOCKED`), so you can run
**many worker processes/replicas across machines against the same Postgres** with no
double-processing and no lost work if one dies (its lease expires and the chunk is
reclaimed). Today the API process also runs the pool; for large batches run additional
replicas/worker processes pointed at the same database. Effective global concurrency is the
**sum** of every replica's `MAX_CONCURRENCY`.

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

The `*_duration_seconds` series are histograms (with `_bucket`/`_sum`/`_count`), so you can
derive p50/p95/p99 latency. Questions these answer at a glance: *throughput* (rate of
`items_processed_total`), *success/failure rate* (by `status`), *whether you're rate-limited*
(`inference_requests_total{outcome="retryable_error"}` + `inference_retries_total` climbing),
*are you saturating the concurrency budget* (`inflight_requests` pinned at `MAX_CONCURRENCY`),
and *API health* (HTTP status mix + latency).

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

## Deployment

### Configuration

All config is environment-driven (`app/core/config.py`), read from real env vars or `.env`.
Provide secrets via your platform's secret manager — never bake them into the image.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://…` — managed Postgres in production |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | Inference endpoint + model |
| `STORAGE_BACKEND` | `local` (dev) or `s3` (DigitalOcean Spaces / S3) |
| `SPACES_*` | Bucket/endpoint/region/key/secret when `STORAGE_BACKEND=s3` |
| `WORKER_POOL_SIZE`, `MAX_CONCURRENCY`, `CHUNK_SIZE` | Throughput tuning (see above) |
| `LOG_FORMAT`, `LOG_LEVEL`, `METRICS_ENABLED`, `SENTRY_DSN` | Observability |

### Single host (Docker Compose)

```bash
cp .env.example .env   # fill in real values
docker compose up -d --build          # postgres + api (migrations auto-applied on start)
docker compose --profile observability up -d   # optional: + Prometheus & Grafana
```

The image (`Dockerfile`) runs as a non-root user, has a `HEALTHCHECK`, and its entrypoint
applies `alembic upgrade head` before serving. On startup the API **resumes** any jobs left
`INGESTING`/`RUNNING` by a previous (crashed) process.

### Production topology

- **Database:** a managed Postgres (e.g. DigitalOcean Managed Databases / RDS). Point
  `DATABASE_URL` at it. It holds the durable queue + job state.
- **Result storage:** set `STORAGE_BACKEND=s3` + `SPACES_*` so chunk results persist to
  DigitalOcean Spaces / S3 (survives container restarts; required if running multiple replicas).
- **Migrations:** run `alembic upgrade head` as a one-off/init step on deploy (the container
  entrypoint already does this; for multi-replica rollouts run it once before scaling up).
- **Scaling out:** run multiple API/worker replicas against the same Postgres — the
  `SKIP LOCKED` queue makes this safe (see [Horizontal scaling](#horizontal-scaling)).
  Behind a load balancer, the `/jobs`, `/status`, `/download` endpoints are stateless reads/writes.
- **Web server:** a single async Uvicorn process is enough for the I/O-bound API. For
  multi-core HTTP throughput, run Gunicorn with Uvicorn workers
  (`gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w <cores>`) or scale replicas.
- **Health & telemetry:** wire `GET /health` to liveness/readiness probes; scrape `GET /metrics`;
  ship stdout JSON logs to your log store; set `SENTRY_DSN` for error aggregation.
- **Secrets:** inject `LLM_API_KEY`, `SPACES_*`, `SENTRY_DSN` via the platform secret store
  (Kubernetes Secrets, DO App Platform env-encrypted vars, etc.).

### CI image

The CI `docker-build` job builds the image on every push. To publish, add a registry login +
`docker push` (e.g. GHCR/DOCR) to `.github/workflows/ci.yml` and deploy that tag.

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
