import pytest

from harness.costs import compute_cost
from harness.models import Usage


def test_sonnet_cost_matches_hand_calculation():
    # 9000 in * $3/M + 5000 out * $15/M = 0.027 + 0.075
    usage = Usage(input_tokens=9_000, output_tokens=5_000)
    assert compute_cost("claude-sonnet-4-6", usage) == pytest.approx(0.102)


def test_batch_halves_cost():
    usage = Usage(input_tokens=9_000, output_tokens=5_000)
    assert compute_cost("claude-sonnet-4-6", usage, batch=True) == pytest.approx(0.051)


def test_cache_read_tokens_cost_one_tenth_of_input():
    plain = compute_cost("claude-sonnet-4-6", Usage(input_tokens=10_000, output_tokens=0))
    cached = compute_cost(
        "claude-sonnet-4-6", Usage(input_tokens=0, output_tokens=0, cache_read_tokens=10_000)
    )
    assert cached == pytest.approx(plain * 0.1)


def test_cache_write_tokens_cost_125_percent_of_input():
    plain = compute_cost("claude-haiku-4-5-20251001", Usage(input_tokens=10_000, output_tokens=0))
    written = compute_cost(
        "claude-haiku-4-5-20251001",
        Usage(input_tokens=0, output_tokens=0, cache_write_tokens=10_000),
    )
    assert written == pytest.approx(plain * 1.25)


def test_unknown_model_fails_fast():
    with pytest.raises(ValueError, match="No pricing known"):
        compute_cost("claude-imaginary-9", Usage(input_tokens=1, output_tokens=1))
