"""Cost accounting for API calls.

Prices are planning-grade as of 2026-06 and must be re-verified against the
live pricing page before the cost model is finalized (plan units U4/U6).
"""

from __future__ import annotations

from dataclasses import dataclass

from harness.models import Usage


@dataclass(frozen=True)
class ModelPricing:
    input_per_mtok: float
    output_per_mtok: float


PRICING: dict[str, ModelPricing] = {
    "claude-opus-4-8": ModelPricing(input_per_mtok=5.0, output_per_mtok=25.0),
    "claude-sonnet-4-6": ModelPricing(input_per_mtok=3.0, output_per_mtok=15.0),
    "claude-haiku-4-5-20251001": ModelPricing(input_per_mtok=1.0, output_per_mtok=5.0),
}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25
BATCH_MULTIPLIER = 0.5


def compute_cost(model: str, usage: Usage, batch: bool = False) -> float:
    """Dollar cost of one call.

    `usage.input_tokens` follows the API convention of excluding cache
    read/write tokens, which are billed at their own multipliers.
    """
    if model not in PRICING:
        raise ValueError(f"No pricing known for model {model!r}; add it to harness.costs.PRICING")
    p = PRICING[model]
    input_cost = (
        usage.input_tokens * p.input_per_mtok
        + usage.cache_read_tokens * p.input_per_mtok * CACHE_READ_MULTIPLIER
        + usage.cache_write_tokens * p.input_per_mtok * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000
    output_cost = usage.output_tokens * p.output_per_mtok / 1_000_000
    total = input_cost + output_cost
    return total * BATCH_MULTIPLIER if batch else total
