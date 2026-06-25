"""Parametrized driver for the batch-translation pipeline (Layer-1, no models).

Encapsulates every deterministic step of
`docs/batch-translation-simulation-runbook.md` so an orchestrating agent only
has to alternate: run a phase here, then spawn the model workers for the next
phase. All model work (mining, consolidation, translation, repair) is done by
subagents the orchestrator spawns — never here.

Phases:
  slice            --source <file> --slug <slug> --n <count>
  normalize        --slug <slug>
  post-consolidate --slug <slug> [--honorifics keep]
  post-translate   --slug <slug>          # prints REPAIR_NEEDED: <ch ...>
  finish           --slug <slug>          # prints RESULT ... and writes outputs
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from harness.adherence import check_adherence
from harness.glossary import clean_mined_terms, merge_mined_terms
from harness.io import load_chapter, load_glossary
from harness.models import ChapterSummary, TranslationContext
from harness.parsing import (
    ParseError,
    parse_extraction_output,
    parse_term_line,
    parse_translation_output,
)
from harness.placeholder import (
    apply_tokens,
    find_invalid_tokens,
    find_new_entity_tokens,
    find_untokenized_enforce_terms,
    fold_glossary_entries,
    fold_new_entities,
    render_glossary_placeholder,
    repair_within_bounds,
)
from harness.prompts import (
    build_user_message,
    load_experiment_prompt,
    load_system_prompt,
    render_glossary_table,
)

BASE = Path("fixtures/corpus/_work")
OUT = Path("fixtures/corpus/translated")
WINDOW = 20


def work(slug: str) -> Path:
    return BASE / slug


def cmd_slice(a: argparse.Namespace) -> None:
    lines = Path(a.source).read_text(encoding="utf-8").splitlines()
    header = re.compile(a.header)
    heads = [i for i, l in enumerate(lines) if header.match(l)]
    if len(heads) < a.n:
        raise SystemExit(f"ERROR: found only {len(heads)} chapter headers matching "
                         f"{a.header!r}; need {a.n}. Check --header.")
    heads.append(len(lines))
    w = work(a.slug)
    for d in ("chapters", "mine_prompt", "mine", "trans_prompt", "trans", "repair_prompt"):
        (w / d).mkdir(parents=True, exist_ok=True)
    mining = load_experiment_prompt("mining_system.md")
    for idx in range(a.n):
        body = "\n".join(lines[heads[idx]:heads[idx + 1]]).rstrip() + "\n"
        name = f"ch{idx + 1:03d}.txt"
        (w / "chapters" / name).write_text(body, encoding="utf-8")
        (w / "mine_prompt" / name).write_text(
            f"{mining}\n\n<chapter>\n{body.strip()}\n</chapter>\n", encoding="utf-8"
        )
    print(f"OK slice: {a.n} chapters -> {w}/chapters and {w}/mine_prompt")


def cmd_normalize(a: argparse.Namespace) -> None:
    w = work(a.slug)
    mined, summaries = [], []
    for f in sorted((w / "mine").glob("ch*.txt")):
        terms, summary = parse_extraction_output(f.read_text(encoding="utf-8"))
        cleaned, _ = clean_mined_terms(terms)
        n = int(f.stem[2:])
        mined.append((n, cleaned))
        summaries.append({"chapter": n, "summary": summary})
    g = merge_mined_terms(mined)
    (w / "summaries.json").write_text(
        json.dumps({"arc_summary": "", "chapter_summaries": summaries}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    instr = (Path("prompts") / "glossary_consolidation.md").read_text(encoding="utf-8")
    (w / "consolidate_prompt.txt").write_text(
        f"{instr}\n\n# Draft glossary ({len(g)} entries)\n\n{render_glossary_table(g)}\n",
        encoding="utf-8",
    )
    print(f"OK normalize: {len(mined)} chapters, {len(g)} draft terms -> consolidate_prompt.txt")


def cmd_post_consolidate(a: argparse.Namespace) -> None:
    w = work(a.slug)
    raw = (w / "glossary_consolidated.txt").read_text(encoding="utf-8")
    block = re.search(r"<glossary>(.*?)</glossary>", raw, re.DOTALL).group(1)
    entries = []
    for line in block.splitlines():
        line = line.strip().strip("`")
        if line and "|" in line and line.upper() != "NONE":
            try:
                entries.append(parse_term_line(line))
            except ParseError:
                pass
    (w / "glossary.json").write_text(
        json.dumps(
            [{"korean": e.korean, "english": e.english, "category": e.category,
              "note": e.note, "enforce": e.enforce} for e in entries],
            ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    glossary = tuple(entries)
    block_text, id_map = render_glossary_placeholder(glossary)
    (w / "token_map.json").write_text(
        json.dumps(id_map, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    sys_text = load_system_prompt(a.honorifics)
    by_ch = {s["chapter"]: s["summary"]
             for s in json.loads((w / "summaries.json").read_text(encoding="utf-8"))["chapter_summaries"]}
    chapters = sorted((w / "chapters").glob("ch*.txt"))
    for f in chapters:
        n = int(f.stem[2:])
        prior = tuple(ChapterSummary(c, by_ch[c]) for c in range(max(1, n - WINDOW), n) if c in by_ch)
        user = build_user_message(TranslationContext(chapter_summaries=prior), load_chapter(f))
        (w / "trans_prompt" / f.name).write_text(
            f"{sys_text}\n\n{block_text}\n\n===== TRANSLATE THIS CHAPTER NOW "
            f"(follow all instructions above) =====\n\n{user}",
            encoding="utf-8",
        )
    soft = sum(1 for e in entries if not e.enforce)
    print(f"OK post-consolidate: {len(entries)} terms ({len(entries) - soft} enforce, "
          f"{soft} soft); {len(chapters)} translation prompts built")


def cmd_post_translate(a: argparse.Namespace) -> None:
    w = work(a.slug)
    glossary = load_glossary(w / "glossary.json")
    token_block, _ = render_glossary_placeholder(glossary)
    repair_instr = (Path("prompts") / "repair.md").read_text(encoding="utf-8")
    need = []
    defects: dict[str, dict] = {}
    for f in sorted((w / "chapters").glob("ch*.txt")):
        src = load_chapter(f)
        res = parse_translation_output((w / "trans" / f.name).read_text(encoding="utf-8"))
        missed = find_untokenized_enforce_terms(src, res.translation, glossary)
        invalid = find_invalid_tokens(res.translation, glossary)
        new_ents = find_new_entity_tokens(res.translation)
        defects[f.stem] = {"forget": [e.korean for e, _ in missed], "invalid": invalid,
                           "new": new_ents}
        if not (missed or invalid):
            continue
        sections = [f"<korean_source>\n{src.strip()}\n</korean_source>",
                    f"<english_translation>\n{res.translation.strip()}\n</english_translation>"]
        if missed:
            sections.append("<missed_entities>\n"
                            + "\n".join(f"{e.korean} | {tok}" for e, tok in missed)
                            + "\n</missed_entities>")
        if invalid:
            sections.append("<invalid_tokens>\n" + "\n".join(sorted(set(invalid)))
                            + "\n</invalid_tokens>")
            sections.append(f"<valid_token_glossary>\n{token_block}\n</valid_token_glossary>")
        (w / "repair_prompt" / f.name).write_text(
            repair_instr + "\n\n" + "\n\n".join(sections) + "\n", encoding="utf-8")
        need.append(f.stem)
    (w / "defects.json").write_text(json.dumps(defects, ensure_ascii=False, indent=1), encoding="utf-8")
    forget_total = sum(len(d["forget"]) for d in defects.values())
    invalid_total = sum(len(d["invalid"]) for d in defects.values())
    new_total = sum(len(d.get("new", [])) for d in defects.values())
    print(f"REPAIR_NEEDED: {' '.join(need) if need else '(none)'}")
    print(f"DEFECTS forget={forget_total} invalid={invalid_total} new_self_reported={new_total}")


def cmd_check_repairs(a: argparse.Namespace) -> None:
    """Detect repairs that failed and should be RE-SPAWNED once (#3).

    A chapter that had a repair_prompt is flagged for retry if its repaired
    file is (a) missing — the worker errored, (b) out of bounds — a collateral
    rewrite, or (c) still carrying unresolved token defects. The orchestrator
    re-spawns the RETRY list once, then proceeds to finish (which falls back to
    the original for anything still unrepaired).
    """
    w = work(a.slug)
    glossary = load_glossary(w / "glossary.json")
    retry = []
    for prompt_file in sorted((w / "repair_prompt").glob("ch*.txt")):
        stem = prompt_file.stem
        src = load_chapter(w / "chapters" / f"{stem}.txt")
        original = parse_translation_output(
            (w / "trans" / f"{stem}.txt").read_text(encoding="utf-8")
        ).translation
        rp = w / "trans" / f"{stem}_repaired.txt"
        if not rp.exists():
            retry.append(stem); continue
        cand = rp.read_text(encoding="utf-8")
        if not repair_within_bounds(original, cand):
            retry.append(stem); continue
        if find_untokenized_enforce_terms(src, cand, glossary) or find_invalid_tokens(cand, glossary):
            retry.append(stem); continue
    print("RETRY:", " ".join(retry) if retry else "(none)")


def cmd_finish(a: argparse.Namespace) -> None:
    w = work(a.slug)
    glossary = load_glossary(w / "glossary.json")
    # Engine builds the full position map (enforce + soft); stray soft-term
    # tokens resolve, only out-of-range ids leak.
    _, id_map = render_glossary_placeholder(glossary)
    defects = json.loads((w / "defects.json").read_text(encoding="utf-8")) if (w / "defects.json").is_file() else {}
    rows, assembled, withheld, repair_rejected = [], [], [], []
    reported_terms = []  # model's <new_glossary_terms> across chapters → fold-back
    tp = tv = leaks = parse_ok = 0
    for f in sorted((w / "chapters").glob("ch*.txt")):
        n = int(f.stem[2:])
        src = load_chapter(f)
        parsed = parse_translation_output((w / "trans" / f.name).read_text(encoding="utf-8"))
        original = parsed.translation
        reported_terms.extend(parsed.new_terms)
        repaired = w / "trans" / f"{f.stem}_repaired.txt"
        # #2 diff-guard: only accept a repair that left the text mostly intact;
        # a wholesale rewrite is rejected and we fall back to the original.
        if repaired.exists():
            cand = repaired.read_text(encoding="utf-8")
            if repair_within_bounds(original, cand):
                translation = cand
            else:
                translation = original
                repair_rejected.append(n)
        else:
            translation = original
        final, leaked = apply_tokens(translation, id_map)
        parse_ok += 1
        d = defects.get(f.stem, {"forget": [], "invalid": []})
        base = {"chapter": n, "forget": len(d["forget"]), "invalid": len(d["invalid"])}
        # FAIL-CLOSED: never ship a chapter that still contains a raw token.
        if leaked:
            leaks += len(leaked)
            withheld.append(n)
            body = (f">>> CHAPTER {n} WITHHELD — unresolved tokens "
                    f"{sorted(set(leaked))}; needs human review <<<")
            rows.append({**base, "status": "NEEDS_HUMAN", "leaked": sorted(set(leaked))})
        else:
            rep = check_adherence(src, final, glossary)
            tp += rep.present
            tv += len(rep.violations)
            body = final.strip()
            rows.append({**base, "status": "ok", "present": rep.present,
                         "violations": [v.korean for v in rep.violations]})
        assembled.append(f"{src.splitlines()[0]}\n\n{body}\n")
    # (b) Fold new entities back into the glossary so future runs pre-tokenise
    # them (deterministic; appends, keeping existing ids stable). Two sources:
    #   1. inline [[NEW:ko|en]] tokens the translator self-reported, and
    #   2. each chapter's <new_glossary_terms> (the reliable channel) — these
    #      carry the model's category/note as-is.
    new_pairs = [tuple(p) for d in defects.values() for p in d.get("new", [])]
    folded, added_tok = fold_new_entities(glossary, new_pairs)
    folded, added_rep = fold_glossary_entries(folded, reported_terms)
    added = added_tok + added_rep
    if added:
        (w / "glossary.json").write_text(json.dumps(
            [{"korean": e.korean, "english": e.english, "category": e.category,
              "note": e.note, "enforce": e.enforce} for e in folded],
            ensure_ascii=False, indent=1), encoding="utf-8")

    OUT.mkdir(exist_ok=True)
    status = "NEEDS_HUMAN" if withheld else "OK"
    stem = f"{a.slug}_ch001-{len(rows):03d}_EN" + ("_INCOMPLETE" if withheld else "")
    out = OUT / f"{stem}.txt"
    out.write_text("\n\n\n".join(assembled), encoding="utf-8")
    pct = (tp - tv) / tp * 100 if tp else 0
    forget_total = sum(len(d["forget"]) for d in defects.values())
    invalid_total = sum(len(d["invalid"]) for d in defects.values())
    report = {"slug": a.slug, "status": status, "chapters": len(rows), "parse_ok": parse_ok,
              "adherence_present": tp, "adherence_ok": tp - tv, "adherence_pct": round(pct),
              "residual_token_leaks": leaks, "withheld_chapters": withheld,
              "repair_rejected_chapters": repair_rejected,
              "new_entities_folded": [e.korean for e in added],
              "defects_total": {"forget_to_tokenize": forget_total, "invalid_token": invalid_total},
              "per_chapter": rows, "output": str(out)}
    (OUT / f"{a.slug}_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"RESULT slug={a.slug} status={status} chapters={len(rows)} parse_ok={parse_ok} "
          f"adherence={tp - tv}/{tp} pct={pct:.0f} residual_leaks={leaks} withheld={withheld} "
          f"repair_rejected={repair_rejected} "
          f"defects_forget={forget_total} defects_invalid={invalid_total} out={out}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("slice"); s.add_argument("--source", required=True)
    s.add_argument("--slug", required=True); s.add_argument("--n", type=int, default=10)
    s.add_argument("--header", default=r"^\d+화(\s|$)",
                   help=r"chapter-header regex; e.g. '^\d+\.\s' for number-dot novels")
    s.set_defaults(fn=cmd_slice)
    for name, fn in (("normalize", cmd_normalize), ("post-translate", cmd_post_translate),
                     ("check-repairs", cmd_check_repairs), ("finish", cmd_finish)):
        q = sub.add_parser(name); q.add_argument("--slug", required=True); q.set_defaults(fn=fn)
    c = sub.add_parser("post-consolidate"); c.add_argument("--slug", required=True)
    c.add_argument("--honorifics", default="keep"); c.set_defaults(fn=cmd_post_consolidate)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
