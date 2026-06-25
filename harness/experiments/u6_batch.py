"""U6 experiment: two-stage backlog pipeline over the live Message Batches API.

Stage 1: mine all chapters with the cheap model in one batch (no glossary —
requests are independent). Normalize renderings (earliest chapter wins).
Stage 2: translate all chapters in a second batch with the merged glossary
and Stage-1 summaries.

Measured: wall-clock per batch, cost at the 50% batch discount, parse and
adherence stats. Batch IDs are printed immediately so an interrupted run can
be inspected with `client.messages.batches.retrieve(<id>)`.

Usage:
    python -m harness.experiments.u6_batch [--novel fixtures/beastworld-favorite] \
        [--model claude-sonnet-4-6] [--mining-model claude-haiku-4-5-20251001]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from harness.adherence import check_adherence
from harness.api import ApiKeyMissing, get_client
from harness.costs import compute_cost
from harness.experiments.common import print_table, save_output
from harness.glossary import clean_mined_terms, merge_mined_terms
from harness.io import load_chapter
from harness.models import ChapterSummary, TranslationContext, Usage
from harness.parsing import ParseError, parse_extraction_output, parse_translation_output
from harness.prompts import (
    build_system_blocks,
    build_system_blocks_for,
    build_user_message,
    load_experiment_prompt,
)
from harness.results import record_call

TAG = "u6-batch"
WINDOW = 3
POLL_SECONDS = 30
MAX_WAIT_SECONDS = 90 * 60


def submit_and_wait(client, label: str, requests: list[dict]) -> dict[str, object]:
    """Submit one batch, poll to completion, return {custom_id: message|error_str}."""
    batch = client.messages.batches.create(requests=requests)
    print(f"[{label}] batch submitted: {batch.id} ({len(requests)} requests)", file=sys.stderr)
    return wait_for_batch(client, label, batch.id)


def wait_for_batch(client, label: str, batch_id: str) -> dict[str, object]:
    """Poll an existing batch to completion; transient network errors retry."""
    import anthropic

    started = time.monotonic()
    while True:
        try:
            status = client.messages.batches.retrieve(batch_id)
            if status.processing_status == "ended":
                break
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            # The batch keeps processing server-side; a dropped poll is not fatal.
            print(f"[{label}] poll failed ({exc.__class__.__name__}), retrying", file=sys.stderr)
        elapsed = time.monotonic() - started
        if elapsed > MAX_WAIT_SECONDS:
            raise TimeoutError(f"[{label}] batch {batch_id} still processing after {elapsed:.0f}s")
        time.sleep(POLL_SECONDS)
    elapsed = time.monotonic() - started
    print(f"[{label}] batch ended after {elapsed:.0f}s", file=sys.stderr)

    out: dict[str, object] = {"_elapsed": elapsed}
    for entry in client.messages.batches.results(batch_id):
        if entry.result.type == "succeeded":
            out[entry.custom_id] = entry.result.message
        else:
            out[entry.custom_id] = f"ERROR: {entry.result.type}"
    return out


def _usage_of(message) -> Usage:
    return Usage(
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        cache_read_tokens=getattr(message.usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(message.usage, "cache_creation_input_tokens", 0) or 0,
    )


def _text_of(message) -> str:
    return "".join(block.text for block in message.content if block.type == "text")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--novel", default="fixtures/beastworld-favorite")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--mining-model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--resume-stage2", metavar="BATCH_ID",
                        help="Skip stage 1; poll an already-submitted stage-2 batch "
                             "and analyze with the glossary saved in results/u6/glossary.json")
    args = parser.parse_args(argv)

    chapter_paths = sorted(str(p) for p in Path(args.novel).glob("ch*.txt"))
    chapters = {p: load_chapter(Path(p)) for p in chapter_paths}

    try:
        client = get_client()
    except ApiKeyMissing as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.resume_stage2:
        from harness.io import load_context

        glossary = load_context(Path("results/u6/glossary.json"), None).glossary
        print(f"resuming with saved glossary: {len(glossary)} terms", file=sys.stderr)
        translate_results = wait_for_batch(client, "stage2-translate", args.resume_stage2)
        mine_results = {"_elapsed": 0.0}
        mine_cost = 0.0
        return _analyze_stage2(args, chapter_paths, chapters, glossary,
                               translate_results, mine_results, mine_cost)

    # Stage 1: mining batch (cheap model, no glossary — independent requests).
    mining_system = load_experiment_prompt("mining_system.md")
    mining_blocks = build_system_blocks_for(mining_system, TranslationContext())
    requests = [
        {
            "custom_id": Path(p).stem,
            "params": {
                "model": args.mining_model,
                "max_tokens": 2000,
                "system": mining_blocks,
                "messages": [{"role": "user",
                              "content": f"<chapter>\n{chapters[p].strip()}\n</chapter>"}],
            },
        }
        for p in chapter_paths
    ]
    mine_results = submit_and_wait(client, "stage1-mine", requests)

    mined = []
    summaries: tuple[ChapterSummary, ...] = ()
    mine_cost = 0.0
    for number, p in enumerate(chapter_paths, 1):
        message = mine_results.get(Path(p).stem)
        if isinstance(message, str) or message is None:
            print(f"stage1 {p}: {message}", file=sys.stderr)
            continue
        usage = _usage_of(message)
        cost = compute_cost(args.mining_model, usage, batch=True)
        mine_cost += cost
        try:
            terms, summary = parse_extraction_output(_text_of(message))
            terms, fixed = clean_mined_terms(terms)
            if fixed:
                print(f"stage1 {p}: cleaned {fixed} indecisive renderings", file=sys.stderr)
            mined.append((number, terms))
            summaries = summaries + (ChapterSummary(number, summary),)
            record_call(TAG, args.mining_model, p, usage, cost, batch=True,
                        extra={"phase": "mine", "terms": len(terms)})
        except ParseError as exc:
            record_call(TAG, args.mining_model, p, usage, cost, batch=True,
                        extra={"phase": "mine", "parse_error": str(exc)})

    glossary = merge_mined_terms(mined)
    print(f"merged glossary: {len(glossary)} unique terms from "
          f"{sum(len(t) for _, t in mined)} mined", file=sys.stderr)
    glossary_file = Path("results/u6/glossary.json")
    glossary_file.parent.mkdir(parents=True, exist_ok=True)
    glossary_file.write_text(
        json.dumps([e.__dict__ for e in glossary], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    # Stage 2: translation batch with the full merged glossary.
    requests = []
    for number, p in enumerate(chapter_paths, 1):
        prior = tuple(s for s in summaries if s.chapter < number)[-WINDOW:]
        context = TranslationContext(glossary, "", prior)
        requests.append({
            "custom_id": Path(p).stem,
            "params": {
                "model": args.model,
                "max_tokens": 16_000,
                "system": build_system_blocks(context),
                "messages": [{"role": "user",
                              "content": build_user_message(context, chapters[p])}],
            },
        })
    translate_results = submit_and_wait(client, "stage2-translate", requests)
    return _analyze_stage2(args, chapter_paths, chapters, glossary,
                           translate_results, mine_results, mine_cost)


def _analyze_stage2(args, chapter_paths, chapters, glossary,
                    translate_results, mine_results, mine_cost) -> int:
    rows = []
    translate_cost = 0.0
    total_present = 0
    total_violations = 0
    for p in chapter_paths:
        message = translate_results.get(Path(p).stem)
        if isinstance(message, str) or message is None:
            rows.append([Path(p).stem, "-", "-", "-", str(message)])
            continue
        usage = _usage_of(message)
        cost = compute_cost(args.model, usage, batch=True)
        translate_cost += cost
        raw = _text_of(message)
        try:
            result = parse_translation_output(raw)
            report = check_adherence(chapters[p], result.translation, glossary)
            total_present += report.present
            total_violations += len(report.violations)
            save_output("translations", "batch", p, raw, base="u6")
            record_call(TAG, args.model, p, usage, cost, batch=True,
                        extra={"phase": "translate", "violations": len(report.violations)})
            rows.append([Path(p).stem, report.present, len(report.violations),
                         f"${cost:.4f}", "ok"])
        except ParseError as exc:
            save_output("translations", "batch", p, f"PARSE ERROR: {exc}\n\n{raw}", base="u6")
            record_call(TAG, args.model, p, usage, cost, batch=True,
                        extra={"phase": "translate", "parse_error": str(exc)})
            rows.append([Path(p).stem, "-", "-", f"${cost:.4f}", "parse error"])

    print()
    print_table(["chapter", "terms_present", "violations", "cost", "status"], rows)
    print(f"\nstage1 (mine, batch): ${mine_cost:.4f} in {mine_results['_elapsed']:.0f}s")
    print(f"stage2 (translate, batch): ${translate_cost:.4f} "
          f"in {translate_results['_elapsed']:.0f}s")
    print(f"total: ${mine_cost + translate_cost:.4f}; "
          f"adherence {total_present - total_violations}/{total_present}")
    print("Outputs: results/u6/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
