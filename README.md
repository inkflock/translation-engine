# Korean → English Web Novel Translation Engine

A production-oriented translation system that renders Korean web novels into
human-level literary English **at scale** (target corpus: ~1M chapters). Built on
the Claude API, with a deterministic Python control layer that coordinates a team
of specialized model agents.

This repository is the validated reference implementation — the architecture,
quality guarantees, and measured results that the production backend (Rust +
Postgres) is built from.

> Built by Inkflock 

---

## Results

Measured on a real chapter run in a single batch (7 novels, 15 chapters each, 25th June 2026):

| Metric | Result | Bar |
| --- | --- | --- |
| Glossary adherence (overall) | **96.81%** | ≥ 92% |
| Enforced-entity accuracy | **100%** | ~100% by construction |
| Raw token leaks reaching output | **0** | 0 |
| Chapters shipped clean (no human review) | **105 of 105** | — |
| Markup integrity (formatting preserved) | **pass** | exact match |

> Enforced proper nouns are accurate **by construction**, not by chance — see
> [zero-drift enforcement] below.

---

## What this is

Prompt-injected glossaries are best-effort: the model sometimes overrides them,
spelling a character's name three different ways across a long novel. Over a
million chapters, that inconsistency is fatal to readability.

This engine makes drift **structurally impossible** for the terms that matter,
and treats translation not as a single model call but as a coordinated pipeline
with measurable quality gates and a fail-closed safety net. The deliverable is
**quality**: consistent naming, preserved honorifics and formatting, and a
guarantee that no defective chapter reaches a reader.

---

## The core idea: zero-drift enforcement

For terms that must never vary (character names, place names, transliterated
proper nouns), the translator does **not** spell them. It emits a placeholder
token — `[[G7]]` — wherever the entity appears, and deterministic code substitutes
the single canonical English spelling afterward. Because the final spelling is
done in code, the model **cannot** drift it.

- **Enforced terms** (proper nouns, transliterations) → tokenized; spelling
  guaranteed by code.
- **Soft terms** (ambiguous or meaning-translated) → plain rendering guidance,
  scored but never locked.
- **Unknown proper nouns** the translator encounters → self-reported in a
  recoverable format so they can be folded into the glossary.
- **Fail-closed gate**: any chapter still carrying a raw token after repair is
  *withheld* and marked for human review rather than shipped. A raw token never
  reaches a reader.

The prompt engineering that drives this is proprietary and not included in this
repository.

---

## Architecture: an orchestrated team of model agents

The system is deliberately split into two layers:

- **A deterministic control layer** (pure Python, fully unit-tested) owns every
  consequential decision: prompt assembly, output parsing, glossary
  merge/clean/dedup, defect detection, adherence scoring, and the fail-closed
  gate. This layer never calls a model — so the logic that determines quality is
  testable and reproducible, not left to chance.
- **A team of specialized model agents**, each assigned the role it's best at,
  coordinated by the control layer:

| Agent role | Model tier | Job |
| --- | --- | --- |
| **Miner** | Sonnet (×N, parallel) | Reads every chapter; extracts glossary terms + continuity summaries |
| **Consolidator** | Opus (×1 per novel) | Entity resolution across the glossary; decides what gets hard-enforced |
| **Translator** | Opus/Sonnet (×N, parallel) | Literary translation in placeholder-token mode |
| **Repairer** | Sonnet (on-defect only) | Surgical re-tokenization of any residual defect |

Model tiers are assigned by economics and task shape, not by default — the kind of
allocation a human team lead makes across specialists, applied to a team of models.

### Pipeline

```

slice → MINE (Sonnet ×N) → normalize → CONSOLIDATE (Opus ×1)
      → TRANSLATE (Opus ×N) → detect defects → REPAIR (Sonnet, on-defect)
      → re-check → finish (apply tokens · score adherence · fail-closed gate)

```

See `docs/pipeline-diagram.mmd` for the full flow and `docs/` for the rationale
behind each step.

---

## Quality gates (enforced every run)

| Check | Bar |
| --- | --- |
| Glossary adherence | ≥ 92% (enforced terms ~100% by construction) |
| Raw token leaks | 0 |
| Unresolved enforcement defects | 0 (else withheld) |
| Parse success | 100% (retry once, then flag) |
| Markup / formatting integrity | exact match, source vs. translation |
| Cross-chapter continuity | consistent naming + chaining summaries |

Anything still unresolved at the final gate sets the run to `NEEDS_HUMAN` and the
chapter is withheld rather than shipped.

---

## Layout

| Path | What it is |
| --- | --- |
| `harness/` | Deterministic control library — all consequential logic, fully tested |
| `scripts/` | Phase driver (coordinates the pipeline; never calls a model directly) |
| `docs/` | Runbook, pipeline diagram, results summaries |
| `tests/` | pytest suite |
| `prompts/` | *Proprietary — not included in this repository* |
| `spec/` | *Proprietary — not included in this repository* |

---

## Note on source material

**No source novels, licensed texts, or generated translations are included in this repository** 
