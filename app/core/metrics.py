"""Prometheus metrics.

These are plain in-process counters/histograms exposed at `/metrics` as text.
No external system is required to collect them — `curl /metrics` works on its
own. Prometheus (optional) is just one possible scraper of that endpoint.
"""
from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# ---- HTTP layer ----
HTTP_REQUESTS = Counter(
    "batch_http_requests_total",
    "HTTP requests handled.",
    ["method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "batch_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)

# ---- Job lifecycle ----
JOBS_SUBMITTED = Counter("batch_jobs_submitted_total", "Jobs accepted via the API.")
JOBS_COMPLETED = Counter(
    "batch_jobs_completed_total", "Jobs that reached a terminal state.", ["state"]
)
INGEST_ITEMS = Counter(
    "batch_ingest_items_total",
    "Items seen during ingestion.",
    ["result"],  # accepted | rejected
)

# ---- Per-row processing ----
ITEMS_PROCESSED = Counter(
    "batch_items_processed_total",
    "Prompt rows finished processing.",
    ["status"],  # SUCCEEDED | FAILED
)
CHUNKS_CLAIMED = Counter(
    "batch_chunks_claimed_total", "Chunks claimed from the work queue."
)
INFLIGHT = Gauge(
    "batch_inflight_requests", "Inference calls currently in flight (backpressure)."
)

# ---- Inference calls ----
INFERENCE_REQUESTS = Counter(
    "batch_inference_requests_total",
    "Inference attempts by outcome.",
    ["model", "outcome"],  # success | retryable_error | permanent_error | unexpected
)
INFERENCE_LATENCY = Histogram(
    "batch_inference_duration_seconds",
    "Per-attempt inference latency in seconds.",
    ["model"],
)
INFERENCE_RETRIES = Counter(
    "batch_inference_retries_total", "Retries triggered by transient failures.", ["model"]
)


def render() -> tuple[bytes, str]:
    """Return (payload, content_type) for the /metrics endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST
