"""U4 experiment: model tier evaluation.

Phase 1: translate each chapter with each candidate model (combined call,
chapter-1 conditions). Phase 2: a judge model compares translations pairwise
per the rubric (eval/rubric.md), blind, with A/B assignment alternated to
control position bias. Phase 3: aggregate report + human review sheet.

Usage:
    python -m harness.experiments.u4_tiers [--judge claude-opus-4-8] [chapters...]
"""

from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path

from harness.api import ApiKeyMissing, call_model, get_client
from harness.costs import compute_cost
from harness.experiments.common import print_table, save_output
from harness.io import load_chapter
from harness.models import TranslationContext
from harness.parsing import (
    ParseError,
    parse_judge_output,
    parse_translation_output,
)
from harness.prompts import (
    build_system_blocks,
    build_system_blocks_for,
    build_user_message,
    load_experiment_prompt,
)
from harness.results import record_call

TAG = "u4-tiers"

MODELS = ("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001")

DEFAULT_CHAPTERS = (
    "fixtures/beastworld-favorite/ch001.txt",
    "fixtures/villainess-shura-field/ch001.txt",
    "fixtures/famine-spring-water/ch001.txt",
)


def short(model: str) -> str:
    for name in ("opus", "sonnet", "haiku"):
        if name in model:
            return name
    return model


def translate_all(client, chapters: list[str]) -> dict:
    """Returns {(chapter, model): translation_text} and prints per-call costs."""
    translations: dict = {}
    context = TranslationContext()
    rows = []
    for chapter_path in chapters:
        chapter = load_chapter(Path(chapter_path))
        for model in MODELS:
            raw, usage = call_model(
                client, model, build_system_blocks(context),
                build_user_message(context, chapter),
            )
            cost = compute_cost(model, usage)
            try:
                result = parse_translation_output(raw)
                translations[(chapter_path, model)] = result.translation
                save_output("translations", short(model), chapter_path, raw, base="u4")
                ok = True
            except ParseError as exc:
                save_output("translations", short(model), chapter_path,
                            f"PARSE ERROR: {exc}\n\n{raw}", base="u4")
                ok = False
            record_call(TAG, model, chapter_path, usage, cost,
                        extra={"phase": "translate", "parse_ok": ok})
            rows.append([Path(chapter_path).parent.name, short(model),
                         usage.output_tokens, f"${cost:.4f}", ok])
            print(f"translated: {chapter_path} [{short(model)}]", file=sys.stderr)
    print_table(["chapter", "model", "out_tokens", "cost", "parse_ok"], rows)
    return translations


def judge_all(client, judge_model: str, chapters: list[str], translations: dict) -> list[dict]:
    judge_system = load_experiment_prompt("judge_system.md")
    verdicts = []
    pairs = list(combinations(MODELS, 2))
    for ci, chapter_path in enumerate(chapters):
        source = load_chapter(Path(chapter_path))
        for pi, (m1, m2) in enumerate(pairs):
            if (chapter_path, m1) not in translations or (chapter_path, m2) not in translations:
                continue
            # Alternate which model is shown as A to control position bias.
            a_model, b_model = (m1, m2) if (ci + pi) % 2 == 0 else (m2, m1)
            user = (
                f"<korean_chapter>\n{source.strip()}\n</korean_chapter>\n\n"
                f"<translation_a>\n{translations[(chapter_path, a_model)]}\n</translation_a>\n\n"
                f"<translation_b>\n{translations[(chapter_path, b_model)]}\n</translation_b>"
            )
            # No temperature: deprecated on the newest models (400 if sent).
            raw, usage = call_model(
                client, judge_model,
                build_system_blocks_for(judge_system, TranslationContext()),
                user, max_tokens=2000,
            )
            cost = compute_cost(judge_model, usage)
            entry = {
                "chapter": chapter_path, "a": short(a_model), "b": short(b_model),
                "winner": "judge_parse_error", "rationale": "", "dimensions": {},
                "cost": cost,
            }
            try:
                parsed = parse_judge_output(raw)
                winner = parsed["overall"]
                entry["winner"] = (
                    "tie" if winner == "tie"
                    else short(a_model) if winner == "A" else short(b_model)
                )
                entry["rationale"] = parsed["rationale"]
                entry["dimensions"] = parsed["dimensions"]
            except ParseError as exc:
                entry["rationale"] = str(exc)
            record_call(TAG, judge_model, chapter_path, usage, cost,
                        extra={"phase": "judge", "a": entry["a"], "b": entry["b"],
                               "winner": entry["winner"]})
            verdicts.append(entry)
            print(f"judged: {Path(chapter_path).parent.name} "
                  f"{entry['a']} vs {entry['b']} -> {entry['winner']}", file=sys.stderr)
    return verdicts


def write_report(chapters: list[str], verdicts: list[dict]) -> Path:
    wins = {short(m): 0 for m in MODELS}
    ties = 0
    lines = ["# U4 model tier evaluation — judge verdicts\n"]
    lines.append("| chapter | pair | winner | accuracy | naturalness | voice |")
    lines.append("|---|---|---|---|---|---|")
    for v in verdicts:
        d = v["dimensions"]
        lines.append(
            f"| {Path(v['chapter']).parent.name} | {v['a']} vs {v['b']} | "
            f"**{v['winner']}** | {d.get('accuracy', '?')} | "
            f"{d.get('naturalness', '?')} | {d.get('voice', '?')} |"
        )
        if v["winner"] in wins:
            wins[v["winner"]] += 1
        elif v["winner"] == "tie":
            ties += 1
    lines.append(f"\nWins: {wins}, ties: {ties}\n\n## Rationales\n")
    for v in verdicts:
        lines.append(f"### {Path(v['chapter']).parent.name}: {v['a']} vs {v['b']} -> "
                     f"{v['winner']}\n{v['rationale']}\n")
    lines.append("\n## Human review\nRead side-by-side under results/u4/translations/"
                 "<model>/ — same filename = same chapter.\n")
    report = Path("results/u4/report.md")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def load_saved_translations(chapters: list[str]) -> dict:
    """Reload phase-1 outputs from results/u4/translations/ (for --judge-only)."""
    translations: dict = {}
    for chapter_path in chapters:
        slug = Path(chapter_path).parent.name + "-" + Path(chapter_path).stem
        for model in MODELS:
            path = Path("results/u4/translations") / short(model) / f"{slug}.md"
            if not path.is_file():
                continue
            try:
                result = parse_translation_output(path.read_text(encoding="utf-8"))
                translations[(chapter_path, model)] = result.translation
            except ParseError as exc:
                print(f"skipping {path}: {exc}", file=sys.stderr)
    return translations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chapters", nargs="*", default=list(DEFAULT_CHAPTERS))
    parser.add_argument("--judge", default="claude-opus-4-8")
    parser.add_argument("--judge-only", action="store_true",
                        help="Skip phase 1; judge saved translations")
    args = parser.parse_args(argv)

    try:
        client = get_client()
    except ApiKeyMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.judge_only:
        translations = load_saved_translations(args.chapters)
        print(f"loaded {len(translations)} saved translations", file=sys.stderr)
    else:
        translations = translate_all(client, args.chapters)
    verdicts = judge_all(client, args.judge, args.chapters, translations)
    report = write_report(args.chapters, verdicts)

    print()
    rows = [[Path(v["chapter"]).parent.name, f"{v['a']} vs {v['b']}", v["winner"],
             f"${v['cost']:.4f}"] for v in verdicts]
    print_table(["chapter", "pair", "winner", "judge_cost"], rows)
    print(f"\nReport: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
