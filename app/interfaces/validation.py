"""Port: validation rule contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from app.domain.models import PromptItem

Severity = Literal["batch_fatal", "row_isolated"]


@dataclass
class ValidationContext:
    """Cross-row context available to rules (e.g. for duplicate detection)."""

    seen_ids: set[str] = field(default_factory=set)


@dataclass
class ValidationOutcome:
    ok: bool
    errors: list[str] = field(default_factory=list)


class ValidationRule(ABC):
    severity: Severity = "row_isolated"

    @abstractmethod
    def check(self, item: PromptItem, ctx: ValidationContext) -> list[str]:
        """Return a list of error messages (empty == passed)."""
