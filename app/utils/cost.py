"""Rough cost estimation for budget guardrails."""
from __future__ import annotations


def estimate_cost_usd(
    prompt_tokens: int,
    output_tokens: int,
    input_price_per_1m: float,
    output_price_per_1m: float,
) -> float:
    """Estimate USD cost for a number of input/output tokens."""
    return (
        prompt_tokens / 1_000_000 * input_price_per_1m
        + output_tokens / 1_000_000 * output_price_per_1m
    )
