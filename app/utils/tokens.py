"""Lightweight token estimation (heuristic, no heavy tokenizer dependency)."""
from __future__ import annotations

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Approximate token count using a chars/4 heuristic."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)
