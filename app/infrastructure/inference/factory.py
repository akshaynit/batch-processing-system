"""Factory for the inference client."""
from __future__ import annotations

from app.core.config import Settings
from app.infrastructure.inference.openai_client import DOInferenceClient
from app.interfaces.inference_client import InferenceClient


def build_inference_client(settings: Settings) -> InferenceClient:
    return DOInferenceClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_seconds,
    )
