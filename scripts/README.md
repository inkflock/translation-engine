# `run_pipeline.py` — batch-translation pipeline driver

The deterministic driver for the two-stage batch translation pipeline. It runs
**only the non-model (Layer-1) steps** — slicing, glossary merge/clean,
consolidation-prompt building, token substitution, defect detection, adherence
scoring, and assembly. It **never calls a model and never spawns agents**; it
just reads and writes files.

The model work (mining, glossary consolidation, translation, repair) is done by
subagents that an **orchestrator** spawns *between* phases. The orchestrator
alternates: run a phase here → spawn the worker round → run the next phase.

All consequential logic lives in the tested `harness/` library that this script
calls, so behaviour is identical no matter who runs the phases. For the *why*
behind each step (model choices, summary-flow nuance, enforce/placeholder/
repair/fail-closed rationale), see
[`docs/batch-translation-simulation-runbook.md`](../docs/batch-translation-simulation-runbook.md).

## Requirements

Run from the repo root with the project venv:

```bash
.venv/bin/python -m scripts.run_pipeline <phase> --slug <slug> [...]
```

## Phases and the file contract

Each phase consumes files and produces the prompt files for the next worker
round (or the final deliverable). The `→ spawn …` rows are where the
**orchestrator** runs model workers — the script does not.

| phase | reads | writes |
|---|---|---|
| `slice --source <file> --slug <s> --n <k> [--header <re>]` | the bundled novel | `chapters/chNNN.txt`, `mine_prompt/chNNN.txt` |
| → spawn **Sonnet** miners | `mine_prompt/chNNN.txt` | `mine/chNNN.txt` |
| `normalize --slug <s>` | `mine/*.txt` | `summaries.json`, `consolidate_prompt.txt` |
| → spawn **1 Opus** consolidator | `consolidate_prompt.txt` | `glossary_consolidated.txt` |
| `post-consolidate --slug <s> [--honorifics keep]` | `glossary_consolidated.txt` | `glossary.json`, `token_map.json`, `trans_prompt/chNNN.txt` |
| → spawn **Opus** translators | `trans_prompt/chNNN.txt` | `trans/chNNN.txt` |
| `post-translate --slug <s>` | `trans/*.txt` | `defects.json`, `repair_prompt/chNNN.txt`; prints `REPAIR_NEEDED:` and `DEFECTS forget= invalid=` |
| → spawn **Sonnet** repairers (only listed chapters) | `repair_prompt/chNNN.txt` | `trans/chNNN_repaired.txt` |
| `finish --slug <s>` | `trans/*` (+ `_repaired`) | deliverable + `<slug>_report.json`; prints `RESULT …` |

Working artifacts live under `fixtures/<corpus>/_work/<slug>/` (gitignored
scratch). The deliverable and report go to `fixtures/<corpus>/translated/`.

## Worked example (one novel, 10 chapters)

```bash
# 1. slice  (use --header for novels delimited as "N. title" instead of "N화")
.venv/bin/python -m scripts.run_pipeline slice \
  --source "fixtures/<corpus>/Example-Novel(001-100).txt" \
  --slug example-novel --n 10 --header '^[0-9]+\. '

# 2. spawn 10 Sonnet miners:  mine_prompt/chNNN.txt -> mine/chNNN.txt

.venv/bin/python -m scripts.run_pipeline normalize --slug example-novel

# 3. spawn 1 Opus consolidator:  consolidate_prompt.txt -> glossary_consolidated.txt

.venv/bin/python -m scripts.run_pipeline post-consolidate --slug example-novel

# 4. spawn 10 Opus translators:  trans_prompt/chNNN.txt -> trans/chNNN.txt

.venv/bin/python -m scripts.run_pipeline post-translate --slug example-novel
#    -> prints e.g.  REPAIR_NEEDED: ch007
#                    DEFECTS forget=1 invalid=0

# 5. spawn Sonnet repairers for the listed chapters:
#       repair_prompt/chNNN.txt -> trans/chNNN_repaired.txt

.venv/bin/python -m scripts.run_pipeline finish --slug example-novel
#    -> writes deliverable + report, prints the RESULT line
```

## Parameters

- `--slug` — short kebab id; namespaces all artifacts so novels never collide.
- `--source` — path to the bundled novel file (chapters concatenated).
- `--n` — number of leading chapters to process.
- `--header` — chapter-header regex. Default `^\d+화(\s|$)`. Use `^[0-9]+\. `
  for novels that delimit chapters as `N. title`.
- `--honorifics` (post-consolidate) — `keep` (default) or `localize`.

## Outputs of `finish`

- `fixtures/<corpus>/translated/<slug>_ch001-0NN_EN.txt` — the assembled
  translation. **Fail-closed:** if any chapter still contains an unresolved
  (out-of-range) token after repair, that chapter's body is replaced with a
  `>>> CHAPTER N WITHHELD … <<<` marker, the file is suffixed `_INCOMPLETE`, and
  the run status is `NEEDS_HUMAN` — a raw token is never shipped.
- `fixtures/<corpus>/translated/<slug>_report.json` — `status`, adherence %,
  `residual_token_leaks`, `withheld_chapters`, per-novel and per-chapter defect
  counts (`forget_to_tokenize`, `invalid_token`).
- The `RESULT …` stdout line summarises all of the above for an orchestrator to
  capture.

## Defect classes (reported per novel and per chapter)

- **forget_to_tokenize** — the translator spelled an `enforce` entity inline
  instead of emitting its token. Routed to repair.
- **invalid_token** — the translator emitted a `[[G<id>]]` with no such glossary
  entry (out of range). Routed to repair; if still unresolved at `finish`, the
  chapter is withheld by the fail-closed gate. (In-range stray tokens for soft
  terms are not defects — they resolve automatically.)
