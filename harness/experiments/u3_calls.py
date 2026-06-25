"""U3 experiment: combined call vs. split calls.

Combined: one call returns translation + new terms + summary (canonical flow).
Split: call 1 translates only; call 2 (same model) extracts terms + summary
from the Korean source plus the finished translation.

Measures: total cost per chapter, parse success, term counts. Translation
quality is judged by a human from the saved outputs in results/u3/calls/.

Usage:
    python -m harness.experiments.u3_calls [--model claude-sonnet-4-6] [chapters...]
"""

from __future__ import annotations

import argparse
import sys

from harness.api import ApiKeyMissing, call_model, get_client
from harness.costs import compute_cost
from harness.experiments.common import DEFAULT_CHAPTERS, print_table, save_output
from harness.io import load_chapter
from harness.models import TranslationContext
from harness.parsing import (
    ParseError,
    parse_extraction_output,
    parse_translation_only,
    parse_translation_output,
)
from harness.prompts import (
    build_system_blocks,
    build_system_blocks_for,
    build_user_message,
    load_experiment_prompt,
    load_system_prompt_with_output,
)
from harness.results import record_call
from pathlib import Path

TAG = "u3-calls"


def run_combined(client, model: str, chapter_path: str, context: TranslationContext) -> dict:
    chapter = load_chapter(Path(chapter_path))
    raw, usage = call_model(
        client, model, build_system_blocks(context), build_user_message(context, chapter)
    )
    cost = compute_cost(model, usage)
    row = {"variant": "combined", "cost": cost, "calls": 1, "parse_ok": True, "terms": 0}
    try:
        result = parse_translation_output(raw)
        row["terms"] = len(result.new_terms)
        save_output("calls", "combined", chapter_path, raw)
    except ParseError as exc:
        row["parse_ok"] = False
        save_output("calls", "combined", chapter_path, f"PARSE ERROR: {exc}\n\n{raw}")
    record_call(TAG, model, chapter_path, usage, cost, extra={"variant": "combined", **row})
    return row


def run_split(client, model: str, chapter_path: str, context: TranslationContext) -> dict:
    chapter = load_chapter(Path(chapter_path))

    translate_system = load_system_prompt_with_output("keep", "output_translation_only.md")
    raw1, usage1 = call_model(
        client,
        model,
        build_system_blocks_for(translate_system, context),
        build_user_message(context, chapter),
    )
    cost1 = compute_cost(model, usage1)
    record_call(TAG, model, chapter_path, usage1, cost1, extra={"variant": "split-translate"})

    row = {"variant": "split", "cost": cost1, "calls": 2, "parse_ok": True, "terms": 0}
    try:
        translation = parse_translation_only(raw1)
    except ParseError as exc:
        row["parse_ok"] = False
        save_output("calls", "split", chapter_path, f"PARSE ERROR (translate): {exc}\n\n{raw1}")
        return row

    extract_user = (
        f"<korean_chapter>\n{chapter.strip()}\n</korean_chapter>\n\n"
        f"<english_translation>\n{translation}\n</english_translation>"
    )
    raw2, usage2 = call_model(
        client,
        model,
        build_system_blocks_for(load_experiment_prompt("extract_system.md"), context),
        extract_user,
    )
    cost2 = compute_cost(model, usage2)
    record_call(TAG, model, chapter_path, usage2, cost2, extra={"variant": "split-extract"})
    row["cost"] = cost1 + cost2

    try:
        terms, summary = parse_extraction_output(raw2)
        row["terms"] = len(terms)
        combined_view = (
            f"{raw1}\n\n=== extraction call ===\n\n{raw2}"
        )
        save_output("calls", "split", chapter_path, combined_view)
    except ParseError as exc:
        row["parse_ok"] = False
        save_output("calls", "split", chapter_path, f"PARSE ERROR (extract): {exc}\n\n{raw2}")
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapters", nargs="*", default=list(DEFAULT_CHAPTERS))
    parser.add_argument("--model", default="claude-sonnet-4-6")
    args = parser.parse_args(argv)

    try:
        client = get_client()
    except ApiKeyMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    context = TranslationContext()  # chapter-1 conditions: no glossary, no summaries
    rows = []
    for chapter_path in args.chapters:
        for runner in (run_combined, run_split):
            r = runner(client, args.model, chapter_path, context)
            rows.append([chapter_path, r["variant"], r["calls"],
                         f"${r['cost']:.4f}", r["parse_ok"], r["terms"]])
            print(f"done: {chapter_path} {r['variant']}", file=sys.stderr)

    print()
    print_table(["chapter", "variant", "calls", "cost", "parse_ok", "new_terms"], rows)
    print("\nOutputs for human review: results/u3/calls/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
