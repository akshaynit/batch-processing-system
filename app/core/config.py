"""Application configuration loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Inference
    llm_base_url: str = "https://inference.do-ai.run/v1/"
    llm_api_key: str = ""
    llm_model: str = "llama3-8b-instruct"
    llm_timeout_seconds: float = 60.0

    # Worker pool / backpressure
    worker_pool_size: int = 4
    max_concurrency: int = 10
    chunk_size: int = 50
    retry_max_attempts: int = 5
    retry_base: float = 1.0
    retry_factor: float = 2.0
    retry_cap: float = 30.0
    lease_ttl_seconds: int = 120
    heartbeat_seconds: int = 30

    # Storage
    storage_backend: str = "local"  # local | s3
    storage_local_root: str = "./data/results"
    spaces_key: str = ""
    spaces_secret: str = ""
    spaces_region: str = ""
    spaces_bucket: str = ""
    spaces_endpoint: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://batch:batch@localhost:5432/batch"

    # Observability
    service_name: str = "batch-processing-system"
    environment: str = "local"
    log_level: str = "INFO"
    log_format: str = "json"  # json | console
    log_file: str = ""  # if set, also write logs to this file (rotating)
    log_file_max_bytes: int = 10_000_000  # rotate at ~10 MB
    log_file_backup_count: int = 5  # keep this many rotated files
    metrics_enabled: bool = True
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0

    # Validation guardrails
    max_items_per_batch: int = 200_000
    max_prompt_tokens: int = 120_000
    max_output_tokens: int = 2048
    min_prompt_chars: int = 1
    cost_budget_usd: float = 50.0
    reject_duplicate_ids: bool = True


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
