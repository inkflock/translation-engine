"""U5 experiment: glossary lifecycle and context flow over consecutive chapters.

Two pipeline variants over the same 10-chapter run:

incremental (real-time mode): chapters translated strictly in order; each
chapter's new terms are appended to the glossary and its summary joins the
context window (last 3 summaries; the arc summary is regenerated every 5
chapters — a scaled-down version of the production window-20/regen-50).

two-stage (backlog mode): Stage 1 mines every chapter independently with a
cheap model (no glossary — parallel-safe), renderings are normalized
(earliest chapter wins); Stage 2 translates every chapter with the full
merged glossary and the Stage-1 summaries.

Measured: glossary growth, whole-run rendering consistency (adherence of
every chapter against the variant's final glossary), cost, and cache reads
on the sequential incremental path.

Usage:
    python -m harness.experiments.u5_lifecycle [--model claude-sonnet-4-6] \
        [--mining-model claude-haiku-4-5-20251001] [--novel fixtures/beastworld-favorite]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.adherence import check_adherence
from harness.api import ApiKeyMissing, call_model, get_client
from harness.costs import compute_cost
from harness.experiments.common import print_table, save_output
from harness.glossary import append_new_terms, merge_mined_terms
from harness.io import load_chapter
from harness.models import ChapterSummary, GlossaryEntry, TranslationContext
from harness.parsing import (
    ParseError,
    parse_arc_summary,
    parse_extraction_output,
    parse_translation_output,
)
from harness.prompts import (
    build_system_blocks,
    build_system_blocks_for,
    build_user_message,
    load_experiment_prompt,
)
from harness.results import record_call

TAG = "u5-lifecycle"
WINDOW = 3
ARC_EVERY = 5
ARC_PROMPT = "arc_summary.md"  # lives in prompts/, not prompts/experiments/


def _translate_with_retry(client, model, context, chapter, chapter_path, variant):
    """One translation call with a single retry on parse failure."""
    for attempt in (1, 2):
        raw, usage = call_model(
            client, model, build_system_blocks(context), build_user_message(context, chapter)
        )
        cost = compute_cost(model, usage)
        try:
            result = parse_translation_output(raw)
            record_call(TAG, model, chapter_path, usage, cost,
                        extra={"variant": variant, "attempt": attempt,
                               "glossary_size": len(context.glossary)})
            return result, raw, cost, usage
        except ParseError as exc:
            record_call(TAG, model, chapter_path, usage, cost,
                        extra={"variant": variant, "attempt": attempt,
                               "parse_error": str(exc)})
            print(f"parse failure (attempt {attempt}): {chapter_path}: {exc}", file=sys.stderr)
    return None, raw, cost, usage


def run_incremental(client, model, arc_model, chapter_paths):
    glossary: tuple[GlossaryEntry, ...] = ()
    summaries: tuple[ChapterSummary, ...] = ()
    arc = ""
    translations: dict[str, str] = {}
    total_cost = 0.0
    cache_reads = []
    growth_rows = []

    for number, chapter_path in enumerate(chapter_paths, 1):
        chapter = load_chapter(Path(chapter_path))
        context = TranslationContext(glossary, arc, summaries[-WINDOW:])
        result, raw, cost, usage = _translate_with_retry(
            client, model, context, chapter, chapter_path, "incremental"
        )
        total_cost += cost
        cache_reads.append(usage.cache_read_tokens)
        if result is None:
            save_output("incremental", "translations", chapter_path,
                        f"PARSE FAILURE\n\n{raw}", base="u5")
            continue
        save_output("incremental", "translations", chapter_path, raw, base="u5")
        translations[chapter_path] = result.translation
        before = len(glossary)
        glossary = append_new_terms(glossary, result.new_terms)
        summaries = summaries + (ChapterSummary(number, result.summary),)
        growth_rows.append([number, len(result.new_terms), len(glossary) - before,
                            len(glossary), usage.cache_read_tokens])
        print(f"incremental ch{number:03d}: glossary {before}->{len(glossary)}",
              file=sys.stderr)

        if number % ARC_EVERY == 0 and number < len(chapter_paths):
            arc_user = (
                f"<current_story_so_far>\n{arc or '(empty)'}\n</current_story_so_far>\n\n"
                "<recent_chapter_summaries>\n"
                + "\n".join(f"Ch.{s.chapter}: {s.summary}" for s in summaries)
                + "\n</recent_chapter_summaries>"
            )
            arc_system = (Path("prompts") / ARC_PROMPT).read_text(encoding="utf-8")
            raw_arc, usage_arc = call_model(
                client, arc_model,
                build_system_blocks_for(arc_system, TranslationContext()),
                arc_user, max_tokens=1000,
            )
            arc_cost = compute_cost(arc_model, usage_arc)
            total_cost += arc_cost
            try:
                arc = parse_arc_summary(raw_arc)
                record_call(TAG, arc_model, f"arc-after-ch{number}", usage_arc, arc_cost,
                            extra={"variant": "incremental", "phase": "arc"})
                print(f"arc summary regenerated after ch{number:03d}", file=sys.stderr)
            except ParseError as exc:
                print(f"arc regen parse failure (keeping old arc): {exc}", file=sys.stderr)

    print("\nincremental glossary growth:")
    print_table(["chapter", "terms_reported", "terms_added", "glossary_size", "cache_read"],
                growth_rows)
    return glossary, translations, total_cost, cache_reads


def run_two_stage(client, model, mining_model, chapter_paths):
    mining_system = load_experiment_prompt("mining_system.md")
    mined: list[tuple[int, tuple[GlossaryEntry, ...]]] = []
    summaries: tuple[ChapterSummary, ...] = ()
    total_cost = 0.0

    for number, chapter_path in enumerate(chapter_paths, 1):
        chapter = load_chapter(Path(chapter_path))
        raw, usage = call_model(
            client, mining_model,
            build_system_blocks_for(mining_system, TranslationContext()),
            f"<chapter>\n{chapter.strip()}\n</chapter>", max_tokens=2000,
        )
        cost = compute_cost(mining_model, usage)
        total_cost += cost
        try:
            terms, summary = parse_extraction_output(raw)
        except ParseError as exc:
            record_call(TAG, mining_model, chapter_path, usage, cost,
                        extra={"variant": "two-stage", "phase": "mine",
                               "parse_error": str(exc)})
            save_output("two-stage", "mining", chapter_path,
                        f"PARSE FAILURE\n\n{raw}", base="u5")
            continue
        record_call(TAG, mining_model, chapter_path, usage, cost,
                    extra={"variant": "two-stage", "phase": "mine", "terms": len(terms)})
        save_output("two-stage", "mining", chapter_path, raw, base="u5")
        mined.append((number, terms))
        summaries = summaries + (ChapterSummary(number, summary),)
        print(f"mined ch{number:03d}: {len(terms)} terms", file=sys.stderr)

    glossary = merge_mined_terms(mined)
    raw_term_count = sum(len(t) for _, t in mined)
    print(f"\nmerged glossary: {raw_term_count} mined -> {len(glossary)} unique",
          file=sys.stderr)

    translations: dict[str, str] = {}
    for number, chapter_path in enumerate(chapter_paths, 1):
        chapter = load_chapter(Path(chapter_path))
        prior = tuple(s for s in summaries if s.chapter < number)[-WINDOW:]
        context = TranslationContext(glossary, "", prior)
        result, raw, cost, _ = _translate_with_retry(
            client, model, context, chapter, chapter_path, "two-stage"
        )
        total_cost += cost
        if result is None:
            save_output("two-stage", "translations", chapter_path,
                        f"PARSE FAILURE\n\n{raw}", base="u5")
            continue
        save_output("two-stage", "translations", chapter_path, raw, base="u5")
        translations[chapter_path] = result.translation
        print(f"two-stage translated ch{number:03d}", file=sys.stderr)

    return glossary, translations, total_cost


def consistency_rows(chapter_paths, translations, glossary):
    rows = []
    total_present = 0
    total_violations = 0
    for chapter_path in chapter_paths:
        if chapter_path not in translations:
            rows.append([Path(chapter_path).stem, "-", "-", "missing translation"])
            continue
        source = load_chapter(Path(chapter_path))
        report = check_adherence(source, translations[chapter_path], glossary)
        total_present += report.present
        total_violations += len(report.violations)
        missed = ", ".join(f"{v.korean}→{v.english}" for v in report.violations) or ""
        rows.append([Path(chapter_path).stem, report.present, len(report.violations), missed])
    return rows, total_present, total_violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--novel", default="fixtures/beastworld-favorite")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--mining-model", default="claude-haiku-4-5-20251001")
    args = parser.parse_args(argv)

    chapter_paths = sorted(str(p) for p in Path(args.novel).glob("ch*.txt"))
    if len(chapter_paths) < 3:
        print(f"error: need >=3 chapters in {args.novel}", file=sys.stderr)
        return 2

    try:
        client = get_client()
    except ApiKeyMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    inc_glossary, inc_translations, inc_cost, cache_reads = run_incremental(
        client, args.model, args.mining_model, chapter_paths
    )
    two_glossary, two_translations, two_cost = run_two_stage(
        client, args.model, args.mining_model, chapter_paths
    )

    print("\n=== whole-run rendering consistency (vs each variant's final glossary) ===")
    for name, translations, glossary, cost in (
        ("incremental", inc_translations, inc_glossary, inc_cost),
        ("two-stage", two_translations, two_glossary, two_cost),
    ):
        rows, present, violations = consistency_rows(chapter_paths, translations, glossary)
        print(f"\n--- {name}: glossary={len(glossary)} terms, "
              f"adherence {present - violations}/{present}, cost ${cost:.4f} ---")
        print_table(["chapter", "terms_present", "violations", "missed"], rows)

    hits = sum(1 for c in cache_reads[1:] if c > 0)
    print(f"\nincremental cache reads: {cache_reads} "
          f"({hits}/{len(cache_reads) - 1} follow-up calls hit cache)")
    print("Outputs: results/u5/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
