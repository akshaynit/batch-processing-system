"""Port: live inference endpoint contract."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.results import InferenceRequest, InferenceResponse


class InferenceClient(ABC):
    """Abstraction over an LLM inference endpoint.

    Implementations: DOInferenceClient (DigitalOcean serverless, OpenAI-compatible),
    MockInferenceClient (tests / local).
    """

    @abstractmethod
    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        """Run a single completion. Raises on transport/HTTP errors."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release any underlying resources (connections)."""
