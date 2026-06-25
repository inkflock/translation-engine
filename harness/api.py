"""Shared live-API helpers for the runner and the U3+ experiments."""

from __future__ import annotations

import os

from harness.env import load_env_file
from harness.models import Usage


class ApiKeyMissing(Exception):
    pass


def require_api_key() -> None:
    """Load .env, then fail fast if ANTHROPIC_API_KEY is still absent."""
    load_env_file()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ApiKeyMissing(
            "ANTHROPIC_API_KEY is not set. Export it, or put "
            "`ANTHROPIC_API_KEY=...` in a .env file at the repo root (gitignored)."
        )


def get_client():
    require_api_key()
    import anthropic

    return anthropic.Anthropic()


def call_model(
    client,
    model: str,
    system_blocks: list[dict],
    user_message: str,
    max_tokens: int = 16_000,
    temperature: float | None = None,
) -> tuple[str, Usage]:
    """One synchronous Messages call; returns (raw_text, usage)."""
    kwargs: dict = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
        **kwargs,
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    usage = Usage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    )
    return raw, usage
