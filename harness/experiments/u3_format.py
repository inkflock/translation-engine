"""U3 experiment: XML-tagged output vs. JSON output.

Runs N repeats of the combined call per format on dialogue-heavy chapters
(quotes stress JSON escaping) and measures parse-failure rate. Saved outputs
let a human check whether JSON escaping degraded the prose itself.

Usage:
    python -m harness.experiments.u3_format [--model ...] [--repeats 3] [chapters...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.api import ApiKeyMissing, call_model, get_client
from harness.costs import compute_cost
from harness.experiments.common import DEFAULT_CHAPTERS, print_table, save_output
from harness.io import load_chapter
from harness.models import TranslationContext
from harness.parsing import ParseError, parse_translation_output, parse_translation_output_json
from harness.prompts import (
    build_system_blocks,
    build_system_blocks_for,
    build_user_message,
    load_system_prompt_with_output,
)
from harness.results import record_call

TAG = "u3-format"


def run_variant(client, model, chapter_path, fmt, repeat) -> dict:
    chapter = load_chapter(Path(chapter_path))
    context = TranslationContext()
    if fmt == "xml":
        system_blocks = build_system_blocks(context)
        parse = parse_translation_output
    else:
        system_blocks = build_system_blocks_for(
            load_system_prompt_with_output("keep", "output_json.md"), context
        )
        parse = parse_translation_output_json

    raw, usage = call_model(client, model, system_blocks, build_user_message(context, chapter))
    cost = compute_cost(model, usage)
    row = {"format": fmt, "repeat": repeat, "cost": cost, "parse_ok": True, "error": ""}
    try:
        parse(raw)
        save_output("format", f"{fmt}-r{repeat}", chapter_path, raw)
    except ParseError as exc:
        row["parse_ok"] = False
        row["error"] = str(exc)[:120]
        save_output("format", f"{fmt}-r{repeat}", chapter_path, f"PARSE ERROR: {exc}\n\n{raw}")
    record_call(TAG, model, chapter_path, usage, cost, extra=row)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapters", nargs="*", default=list(DEFAULT_CHAPTERS))
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)

    try:
        client = get_client()
    except ApiKeyMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows = []
    for chapter_path in args.chapters:
        for fmt in ("xml", "json"):
            for repeat in range(1, args.repeats + 1):
                r = run_variant(client, args.model, chapter_path, fmt, repeat)
                rows.append([chapter_path, fmt, repeat, f"${r['cost']:.4f}",
                             r["parse_ok"], r["error"]])
                print(f"done: {chapter_path} {fmt} r{repeat}", file=sys.stderr)

    print()
    print_table(["chapter", "format", "repeat", "cost", "parse_ok", "error"], rows)
    failures = {(fmt): sum(1 for r in rows if r[1] == fmt and not r[4]) for fmt in ("xml", "json")}
    total = len(args.chapters) * args.repeats
    print(f"\nparse failures: xml {failures['xml']}/{total}, json {failures['json']}/{total}")
    print("Outputs for human review: results/u3/format/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
