# Korean→English Webnovel Translation System — What We Did and What We Learned

*June 9-10, 2026 · ~8 min read*

> **Licensing context.** This work was carried out on Korean web novel IP that
> Inkflock has **licensed non-exclusively via revenue share** through its content
> partners. No source novels or generated translations are included in this
> repository — they are supplied at run time and excluded from version control.
> Any novel titles, character names, or term examples below are neutral
> placeholders (`Example-Novel`, `Character-A`, `term-X`).

## The goal

Build a system that translates Korean webnovels into English at **human level** — prose a paying reader wouldn't suspect of being machine translation — as cheaply as that bar allows. The scale is serious: ~1,000 novels × ~1,000 chapters ≈ **1 million chapters**, each 2-3 A4 pages of Korean.

Every translated chapter must produce three things:

1. The **English chapter text**
2. **New glossary terms** — names, places, techniques that need a fixed rendering in future chapters
3. A **1-2 sentence chapter summary** for continuity

The production system will be a Rust backend with Postgres storage — that gets written later, by hand. The work documented here answered the question that comes *before* the backend: **what is the right way to translate, and what does it cost?** We answered it by building a small Python test harness and spending ~$4.20 of API credit on controlled experiments against real chapters.

## How we worked

Instead of trusting intuition, every design decision was framed as a measurable question, and a throwaway experiment was built for each. Real fixtures: 10 consecutive chapters of one novel plus single chapters from three other genres. Every API call logged its tokens and cost to JSONL files; every translation was saved for human reading.

Seven units of work: U1-U2 built the harness and prompts, U3-U6 ran the experiments, U7 wrote the handoff specification.

## The experiments and what they showed

### U3 — How should the call be structured? ($1.23)

**One call or two?** We compared a single call returning all three outputs against a split design (translate first, then a second call extracts terms and summary). The split costs **~40% more** — the extraction call has to re-read the whole chapter plus its translation as input — and produced no better terms or summaries. *One combined call per chapter wins.*

**XML tags or JSON?** Long literary text inside JSON strings must escape every quote and newline, and dialogue-heavy webnovel chapters are full of quotes. Measured over 6 runs each: XML-tagged sections parsed **6/6**; JSON failed **1/6** (a missed quote escape — exactly the predicted failure) and cost 10-15% more due to escaping overhead. *XML sections win.*

**Does the model actually obey a glossary?** We gave it a 50-term glossary in the prompt (16 of those terms actually occur in the test chapter, 34 were decoys) and counted rendering mismatches. Result: **zero violations, twice in a row**. Every established term was rendered exactly as specified. This also confirmed the design choice to inject the glossary as a prompt table rather than pre-replacing words in the Korean source — replacement would corrupt Korean grammar, since particles like 이/가 and 은/는 attach to words based on their final sound.

### U4 — Which model translates? ($1.29, the most important decision)

Three model tiers translated the same three chapters from different genres. Then the strongest model (Opus) judged the translations **blind, pairwise** — it never knew which model produced which text, and A/B positions were alternated to cancel position bias.

| | wins | avg cost/chapter | verdict |
|---|---|---|---|
| Opus 4.8 | 5 | $0.126 | best, by a narrow margin |
| Sonnet 4.6 | 4 | $0.061 | ties Opus on accuracy, won once outright |
| Haiku 4.5 | 0 | $0.020 | **disqualified** |

Haiku lost every single pairing, and not on style: it made **substantive accuracy errors in every judged chapter** — inverted the meaning of a sentence to the opposite of the source, turned one small number into a much larger one, mistranslated a concrete object into an unrelated one, and drifted between two spellings of a character's name within one chapter. (Specific examples are omitted here to avoid reproducing licensed prose.) No glossary can fix wrong meaning, which also killed the idea of a "Sonnet for early chapters, Haiku afterward" hybrid.

Opus's wins over Sonnet came mostly from name-rendering consistency in these *no-glossary* test conditions — and consistency is exactly what the production glossary provides for free. With accuracy essentially tied and prose quality trading blows, **Sonnet 4.6 at 48% of Opus's price is the default translator**. Opus remains available as a ~2× premium option for novels that deserve it.

A bonus discovery: given no glossary, the three models romanized the same character's name three different ways — a pinyin form (Opus recognized the novel is Chinese in origin), a hybrid form (Sonnet), and a Korean-style form (Haiku). Consistency cannot come from the model; it must come from the glossary. This validated the entire glossary-first architecture.

### U5 — Does the glossary lifecycle actually work over many chapters? ($1.29)

The real test: 10 *consecutive* chapters of one novel, translated start to finish in **incremental mode** — each chapter's new terms appended to the glossary, each summary joining a rolling context window, with the "story so far" arc summary regenerated periodically.

Results:

- **Glossary growth converges.** Chapter 1 produced 12 terms; later chapters added 0-5 each; 28 total after 10 chapters. The model genuinely reports only *new* terms — the glossary won't balloon to thousands of junk entries by chapter 1,000.
- **96% whole-run rendering consistency** (97 of 101 term occurrences), with **zero character-name drift after chapter 1**. The four misses were stylistic near-misses like "bone-blade" vs "bone knife."
- **Continuity holds.** Chapter 10's translation correctly carried relationships, plot threads, and lore established in chapters 1-9, and the context stayed bounded (~2K tokens) thanks to the window + arc-summary compression.
- Two calls out of 21 needed their single retry — both because the model wrote `NONE (no new terms...)` with commentary where the format demanded bare `NONE`. The parser now tolerates that; the prompt format is otherwise rock-solid.

### U6 — Does the bulk pipeline work on the real Batch API? ($0.32)

For ingesting a novel's backlog, translating chapters one-by-one would be slow (chapter N+1 needs chapter N's glossary) and inconsistent in early chapters. The designed solution is **two-stage**: Stage 1 sends *every* chapter independently through cheap Haiku "mining" (extract term candidates + summary, no translation), merges the results into one whole-novel glossary; Stage 2 then translates *all* chapters in parallel with that complete glossary. Both stages run on the Batch API at a **50% discount**.

The pilot ran both stages live on the 10-chapter novel:

- **Mechanics: flawless.** 20/20 requests succeeded, results mapped back correctly, the mining batch finished in 61 seconds and the translation batch in 122 seconds (the API only promises 24 hours — design for that, enjoy the 2 minutes).
- **Cost: $0.032 per chapter all-in** ($0.0033 mining + $0.0287 translation).
- **One real weakness, found, understood, and fixed.** With the raw Haiku-mined glossary, rendering consistency dropped to 70% (81/116). The violations weren't random translation drift — they traced to a *handful of defective glossary entries* repeated across chapters: indecisive renderings carrying a slash (e.g. `term-X → settlement/tribe`, impossible to match verbatim) and opaque romanizations the translator kept overriding in favor of a meaning-based rendering.

  A follow-up A/B on the same chapters settled it without needing any human review step: **mining with Sonnet plus an automatic cleaner** for indecisive renderings lifted adherence to **92% (119/129) with zero name violations** — every remaining mismatch was an address/rank term the translator legitimately varies by speech register (e.g. two acceptable English forms of address for the same honorific). Sonnet mining costs $0.0104/chapter batched vs Haiku's $0.0033 — about $7K more across the full corpus, well worth 70%→92%. The two-stage pipeline is now **fully automated**: mine (Sonnet) → auto-clean → translate.

## The bottom line

**The system, in one paragraph:** each chapter is one Sonnet 4.6 call. The system prompt (translator persona + style rules + honorifics policy) and the append-only glossary table are cached blocks; the user message carries the story-so-far summary, the last ~20 chapter summaries, and the Korean chapter; the model returns `<translation>`, `<new_glossary_terms>`, `<chapter_summary>`. Backlogs run as two Batch-API stages (mine → normalize → translate, fully parallel); newly published chapters run synchronously and append their terms and summary afterward.

**The cost:**

| scenario | per chapter | per 1M chapters |
|---|---|---|
| Backlog (batch, Sonnet mining included) | ~$0.036 | **~$36,000** |
| Real-time new chapter (sync) | ~$0.06 | — |
| Opus premium novel | ~2.1× Sonnet | — |

For context, the original plan estimated ~$51K for Sonnet — the measured number came in ~40% lower (chapters produce ~3K output tokens, not the assumed ~6K).

## What's left for a human to decide

1. **Honorifics policy** — keep romanized (-nim, oppa, hyung) or localize into English address. Both prompt variants exist; read the sample translations and pick. Per-corpus configuration, not architecture.
2. **Name romanization for Chinese-origin novels** — much of the Korean webnovel corpus is translated Chinese fiction; choose pinyin or Korean style per source. The glossary enforces whichever you pick.
3. **Spot-check quality yourself.** An LLM judged the tier comparison; a human (you) should read a few sample chapters to confirm the bar is met.
4. **Reconcile the billing console** against the computed ~$4.14 — pricing constants in `harness/costs.py` should be verified against your actual invoice once.

## Where everything lives

| artifact | path |
|---|---|
| Architecture & pipeline rationale | `docs/` |
| Pipeline diagram | `docs/pipeline-diagram.mmd` |
| Design plan with measured evidence in every decision | `docs/plans/2026-06-09-001-…-plan.md` |
| Production prompts | *proprietary — not included in this repository* |
| Source texts, translations, per-call cost logs | supplied at run time; excluded from version control |
| Deterministic control library + test suite | `harness/`, `tests/` |

> *Note: this document is a curated public showcase. The proprietary prompt files,
> backend handoff specification, and any licensed source/translation artifacts
> referenced during the original work are intentionally excluded.*
