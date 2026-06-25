"""Append-only JSONL logging so experiment runs stay comparable."""

from __future__ import annotations

import json
import time
from pathlib import Path

from harness.models import Usage

RESULTS_DIR = Path("results")


def record_call(
    tag: str,
    model: str,
    chapter_path: str,
    usage: Usage,
    cost: float,
    batch: bool = False,
    extra: dict | None = None,
) -> Path:
    """Append one call record to results/<tag>.jsonl and return the file path."""
    RESULTS_DIR.mkdir(exist_ok=True)
    out_file = RESULTS_DIR / f"{tag}.jsonl"
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tag": tag,
        "model": model,
        "chapter": chapter_path,
        "batch": batch,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "cost_usd": round(cost, 6),
        **(extra or {}),
    }
    with out_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return out_file
