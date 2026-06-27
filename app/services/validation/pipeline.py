"""ValidationPipeline: composite over ValidationRule instances."""
from __future__ import annotations

from app.domain.models import PromptItem
from app.interfaces.validation import (
    ValidationContext,
    ValidationOutcome,
    ValidationRule,
)


class ValidationPipeline:
    def __init__(self, rules: list[ValidationRule]) -> None:
        self.rules = rules

    def validate_item(
        self, item: PromptItem, ctx: ValidationContext
    ) -> ValidationOutcome:
        errors: list[str] = []
        for rule in self.rules:
            errors.extend(rule.check(item, ctx))
        return ValidationOutcome(ok=not errors, errors=errors)
