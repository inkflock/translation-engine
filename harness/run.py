"""Translate one chapter: assemble prompt, call the API, print and record results.

Usage:
    python -m harness.run fixtures/<novel>/ch001.txt \
        [--glossary glossary.json] [--summaries summaries.json] \
        [--model claude-sonnet-4-6] [--honorifics keep|localize] \
        [--tag label] [--dry-run]

--dry-run prints the assembled prompt and a rough token estimate without
calling the API (no API key needed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.api import ApiKeyMissing, call_model, get_client
from harness.costs import compute_cost
from harness.io import InputError, load_chapter, load_context
from harness.parsing import ParseError, parse_translation_output
from harness.prompts import build_system_blocks, build_user_message
from harness.results import record_call

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 16_000


def _rough_token_estimate(text: str) -> int:
    # Heuristic only, for dry-run sizing: ~1 token per Hangul syllable,
    # ~4 chars per token for Latin text.
    hangul = sum(1 for c in text if "가" <= c <= "힣")
    other = len(text) - hangul
    return hangul + other // 4


def translate_chapter(args: argparse.Namespace) -> int:
    chapter_text = load_chapter(Path(args.chapter))
    context = load_context(
        Path(args.glossary) if args.glossary else None,
        Path(args.summaries) if args.summaries else None,
    )
    system_blocks = build_system_blocks(context, honorifics=args.honorifics)
    user_message = build_user_message(context, chapter_text)

    if args.dry_run:
        full = "\n\n---\n\n".join([b["text"] for b in system_blocks] + [user_message])
        print(full)
        print(f"\n[dry-run] rough input estimate: ~{_rough_token_estimate(full)} tokens", file=sys.stderr)
        return 0

    try:
        client = get_client()
    except ApiKeyMissing as exc:
        print(f"error: {exc} (use --dry-run to skip the API call)", file=sys.stderr)
        return 2

    raw, usage = call_model(
        client, args.model, system_blocks, user_message, max_tokens=MAX_OUTPUT_TOKENS
    )
    cost = compute_cost(args.model, usage)

    try:
        result = parse_translation_output(raw)
    except ParseError as exc:
        record_call(args.tag, args.model, args.chapter, usage, cost, extra={"parse_error": str(exc)})
        print(f"error: output failed to parse: {exc}\n\n--- raw output ---\n{raw}", file=sys.stderr)
        return 1

    print(result.translation)
    print("\n=== new glossary terms ===")
    for term in result.new_terms:
        print(f"{term.korean} | {term.english} | {term.category} | {term.note}".rstrip(" |"))
    if not result.new_terms:
        print("(none)")
    print(f"\n=== chapter summary ===\n{result.summary}")

    out = record_call(
        args.tag,
        args.model,
        args.chapter,
        usage,
        cost,
        extra={"honorifics": args.honorifics, "new_terms": len(result.new_terms)},
    )
    print(
        f"\n[{args.model}] in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_read={usage.cache_read_tokens} cost=${cost:.4f} -> {out}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translate one Korean webnovel chapter.")
    parser.add_argument("chapter", help="Path to the Korean chapter text file")
    parser.add_argument("--glossary", help="Path to glossary JSON (append-ordered entry list)")
    parser.add_argument("--summaries", help="Path to summaries JSON (arc_summary + chapter_summaries)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--honorifics", choices=["keep", "localize"], default="keep")
    parser.add_argument("--tag", default="adhoc", help="Results file tag (results/<tag>.jsonl)")
    parser.add_argument("--dry-run", action="store_true", help="Print assembled prompt, no API call")
    args = parser.parse_args(argv)
    try:
        return translate_chapter(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
