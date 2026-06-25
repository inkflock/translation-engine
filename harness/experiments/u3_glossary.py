"""U3 experiment: glossary adherence under load.

Translates a chapter with a 50-term glossary in the prompt (a subset of the
terms actually occur in the chapter) and counts rendering mismatches —
glossary terms present in the Korean source whose established English
rendering does not appear in the translation. Target: zero violations.

Usage:
    python -m harness.experiments.u3_glossary [--model ...] [--repeats 2] \
        [--chapter fixtures/beastworld-favorite/ch001.txt] \
        [--glossary fixtures/beastworld-favorite/glossary_load50.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.adherence import check_adherence
from harness.api import ApiKeyMissing, call_model, get_client
from harness.costs import compute_cost
from harness.experiments.common import print_table, save_output
from harness.io import load_chapter, load_context
from harness.parsing import ParseError, parse_translation_output
from harness.prompts import build_system_blocks, build_user_message
from harness.results import record_call

TAG = "u3-glossary"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", default="fixtures/beastworld-favorite/ch001.txt")
    parser.add_argument("--glossary", default="fixtures/beastworld-favorite/glossary_load50.json")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args(argv)

    chapter = load_chapter(Path(args.chapter))
    context = load_context(Path(args.glossary), None)
    print(f"glossary terms: {len(context.glossary)}", file=sys.stderr)

    try:
        client = get_client()
    except ApiKeyMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows = []
    for repeat in range(1, args.repeats + 1):
        raw, usage = call_model(
            client, args.model, build_system_blocks(context),
            build_user_message(context, chapter),
        )
        cost = compute_cost(args.model, usage)
        try:
            result = parse_translation_output(raw)
        except ParseError as exc:
            record_call(TAG, args.model, args.chapter, usage, cost,
                        extra={"repeat": repeat, "parse_error": str(exc)})
            save_output("glossary", f"r{repeat}", args.chapter, f"PARSE ERROR: {exc}\n\n{raw}")
            rows.append([repeat, "-", "-", "parse error", f"${cost:.4f}"])
            continue

        report = check_adherence(chapter, result.translation, context.glossary)
        violation_names = ", ".join(
            f"{v.korean}→{v.english}" for v in report.violations
        ) or "none"
        record_call(
            TAG, args.model, args.chapter, usage, cost,
            extra={
                "repeat": repeat,
                "terms_in_prompt": len(context.glossary),
                "terms_present": report.present,
                "violations": [v.korean for v in report.violations],
            },
        )
        save_output("glossary", f"r{repeat}", args.chapter, raw)
        rows.append([repeat, report.present, len(report.violations), violation_names,
                     f"${cost:.4f}"])
        print(f"done: repeat {repeat}", file=sys.stderr)

    print()
    print_table(["repeat", "terms_present", "violations", "missed_renderings", "cost"], rows)
    print("\nOutputs for human review: results/u3/glossary/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
