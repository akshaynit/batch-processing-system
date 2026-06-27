"""Concrete validation rules (row-isolated and batch-fatal)."""
from __future__ import annotations

from app.domain.models import PromptItem
from app.interfaces.validation import ValidationContext, ValidationRule


class NonEmptyExternalId(ValidationRule):
    severity = "row_isolated"

    def check(self, item: PromptItem, ctx: ValidationContext) -> list[str]:
        if not item.external_id or not item.external_id.strip():
            return ["missing or empty external id"]
        return []


class NonEmptyPrompt(ValidationRule):
    severity = "row_isolated"

    def __init__(self, min_chars: int = 1) -> None:
        self.min_chars = min_chars

    def check(self, item: PromptItem, ctx: ValidationContext) -> list[str]:
        text = (item.prompt or "").strip()
        if len(text) < self.min_chars:
            return [f"prompt shorter than min_chars={self.min_chars}"]
        return []


class MaxPromptTokens(ValidationRule):
    """Approximate token guard (chars/4 heuristic) vs the context window."""

    severity = "row_isolated"

    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens

    def check(self, item: PromptItem, ctx: ValidationContext) -> list[str]:
        approx_tokens = len(item.prompt or "") // 4
        if approx_tokens > self.max_tokens:
            return [f"prompt ~{approx_tokens} tokens exceeds max {self.max_tokens}"]
        return []


class UniqueExternalId(ValidationRule):
    severity = "row_isolated"

    def check(self, item: PromptItem, ctx: ValidationContext) -> list[str]:
        if item.external_id in ctx.seen_ids:
            return [f"duplicate external id: {item.external_id}"]
        ctx.seen_ids.add(item.external_id)
        return []
