# Runbook: Batch Translation Pipeline Simulation (subscription, no API)

> **Licensing context.** This procedure runs against Korean web novel IP that
> Inkflock has **licensed non-exclusively via revenue share** through its content
> partners. No source novels or generated translations are stored in this
> repository; they are supplied at run time by the operator and excluded from
> version control. Novel titles and character names below are neutral
> placeholders (`Example-Novel`, `Character-A`).

A repeatable procedure for translating a Korean web novel through the project's
**two-stage batch pipeline** on a Claude **subscription** instead of API tokens.

Use this to spot-check translation quality and pipeline behavior on real
chapters before committing to a paid production run.

## How this maps onto the harness (two layers)

The harness is two layers, and only one of them touches the API:

- **Layer 1 — deterministic logic (pure Python, no API key, unit-tested).**
  `prompts.py`, `parsing.py`, `glossary.py`, `adherence.py`, `io.py`,
  `models.py`. This is where our *decisions* live: prompt assembly + order,
  output parsing, glossary merge/clean/dedup, adherence scoring.
  **→ We RUN this real code via `.venv/bin/python`. It is not simulated and
  costs nothing.**
- **Layer 2 — model invocation (`api.py`, `experiments/u6_batch.py`).** The
  only code that bills API tokens.
  **→ This is the ONLY part replaced by subagents** (Agent tool, subscription).

So a subagent is dropped in exactly where `api.py` used to sit. Everything
around it — assembling the prompt the subagent receives, parsing what it
returns, merging/cleaning the glossary, scoring adherence — is the real
harness. `costs.py` is the only module with no meaning under subscription
(it is API per-token pricing); ignore it.

The orchestrator (main agent) runs Layer-1 functions and coordinates;
**all LLM work — mining and translation — is delegated to subagents.**

---

## Parameters (set per run)

| Param | Default | Notes |
|---|---|---|
| `SOURCE` | — | Path to the bundled novel file (chapters concatenated) |
| `NOVEL_SLUG` | — | Short kebab id for the novel (e.g. `example-novel`); namespaces all artifacts so novels never collide |
| `CHAPTER_COUNT` | 20 | How many leading chapters to process |
| `MINING_MODEL` | `sonnet` | Stage-1 glossary + summary extraction (reads every chapter) |
| `CONSOLIDATION_MODEL` | `opus` | Step-3b glossary consolidation + enforce-tagging (reads only the glossary, 1 call/novel) |
| `TRANSLATION_MODEL` | `opus` | Stage-2 translation + final summary (placeholder-token mode) |
| `REPAIR_MODEL` | `sonnet` | Step-4b surgical re-tokenize of any forget-to-tokenize residual |
| `HONORIFICS` | `keep` | `keep` (romanized -nim/-ssi/hyung…) or `localize` |
| `SUMMARY_WINDOW` | 20 | Prior chapter summaries fed into each translation (production default; fewer if run is short) |
| `WORK_DIR` | `fixtures/<corpus>/_work/<NOVEL_SLUG>` | Sliced chapters + intermediate artifacts; **per-novel** so runs never collide |
| `OUT_DIR` | `fixtures/<corpus>/translated` | Final concatenated translation, filename prefixed with `<NOVEL_SLUG>` |

Chapters in the bundled file are delimited by headers matching `^[0-9]+화 `.

`_work/` is gitignored, reproducible scratch — safe to delete; the deliverables
(translated file, `glossary.json`, validation report) are written to `OUT_DIR`.
Namespacing by `NOVEL_SLUG` keeps every processed novel independently
re-scorable without re-spawning agents.

---

## Model assignment (rationale)

- **Sonnet 4.6 mines** (Stage 1): mining reads every chapter, so input volume
  dominates cost over a 1M-chapter corpus — use the cheaper tier.
- **Opus 4.8 consolidates the glossary** (between stages): runs ONCE per novel
  and reads ONLY the merged glossary (~2K tokens, never the chapters), so the
  cost lever that forced Sonnet for mining is absent (~$0.05/novel at Opus).
  It is a reasoning-heavy entity-resolution/transliteration task, and using the
  same model as the translator makes the glossary agree with how Opus actually
  writes. → use Opus.
- **Opus 4.8 translates** (Stage 2): chosen here for **maximum quality** when
  cost is not the constraint. (Production default is Sonnet 4.6 at ~½ the cost;
  Opus is the premium option — see U4.)

---

## Summary flow in BATCH mode (important)

Batch Stage 2 is **fully parallel**, so the per-chapter summaries that provide
continuity must exist *before* translation starts. Therefore:

- **Continuity summaries come from Stage-1 (Sonnet) mining.** Chapter N's
  translation receives the window of prior Stage-1 summaries (chapters
  `N-WINDOW … N-1`).
- **Opus writes the final canonical per-chapter summary** as part of its
  combined translation call (output, not fed back within the batch).

Opus summaries feeding the *next* chapter's translation is inherently a
**sequential / non-batch (real-time)** behavior. If that is wanted, run the
incremental pipeline instead, not this batch one.

---

## Procedure

### Step 0 — Setup (one-time / when prompts change)
- Ensure `prompts/system.md` has the **Markup and formatting** section
  (preserve `@it[…]`, `@b<…>`, `@b(N)@`, bare `@it` SFX lines verbatim;
  translate only human-readable text).
- Ensure the mining prompt (`prompts/experiments/mining_system.md`) has a
  matching note: **ignore markup tokens; never propose them as terms.**

Each step is tagged **[harness]** (run real Layer-1 code), **[subagent]**
(Layer-2 model work on subscription), or **[orchestrator]** (glue).

### Step 1 — Slice  **[orchestrator]**
- Locate the first `CHAPTER_COUNT` chapter headers (`^[0-9]+화 `) in `SOURCE`.
- Write each chapter (header through the line before the next header) to
  `WORK_DIR/chNNN.txt` (UTF-8, zero-padded NNN).

### Step 2 — Stage 1: Mine  **[subagent: `MINING_MODEL`, parallel, one per chapter]**
- **[harness]** build the mining prompt with `load_experiment_prompt(
  "mining_system.md")` + the chapter text loaded via `io.load_chapter`.
- **[subagent]** each Sonnet agent receives that prompt + one chapter (no
  glossary → parallel-safe) and returns the two mining sections:
  `<new_glossary_terms>` (`korean | english | category | note`, or `NONE`) and
  `<chapter_summary>`. Writes raw reply to `WORK_DIR/mine/chNNN.txt`.
- **[harness]** parse each reply with `parsing.parse_extraction_output` →
  `(terms, summary)`.

### Step 3 — Normalize  **[harness]**
- `glossary.clean_mined_terms` on each chapter's terms (slash/paren →
  first alternative).
- `glossary.merge_mined_terms([(chapter_no, terms), …])` → canonical glossary
  (**dedupe by Korean, earliest chapter wins**). Persist to
  `WORK_DIR/glossary.json`.
- Order the Stage-1 summaries into a continuity timeline
  `WORK_DIR/summaries.json` (list of `{chapter, summary}`).

### Step 3b — Consolidate glossary  **[subagent: Opus, one call per novel]**
The deterministic merge (Step 3) collapses exact-key variants but cannot
resolve *semantic* fragmentation across different keys — same entity spelled
differently (`Pedebaek` vs `Featherback`), opaque romanizations (`Macheang`
for 魔倉 = "Magic Warehouse"), or junk rows. A single reasoning pass fixes
these.
- **[harness]** render the merged glossary as a table (`render_glossary_table`)
  into `prompts/glossary_consolidation.md` → `WORK_DIR/consolidate_prompt.txt`.
- **[subagent: Opus]** returns one `<glossary>` section: deduped, one canonical
  rendering per entity, meaning preferred over bad romanization, junk dropped,
  distinct title-vs-person entries kept separate. **Each entry also gets an
  `enforce` flag** (`korean | english | category | note | enforce`): `yes` for
  unambiguous proper nouns (hard-locked downstream), `no` for homonyms /
  substrings-of-common-words / context-dependent terms (e.g. `민주`, which
  occurs inside `민주화` = "democratization"). Writes
  `WORK_DIR/glossary_consolidated.txt`.
- **[harness]** parse via `parse_term_line` (reads the `enforce` field) →
  canonical `WORK_DIR/glossary.json`.

> Measurement note: consolidation must run **before** Stage 2. Re-scoring
> translations made with a *pre-consolidation* glossary against the
> consolidated one understates quality — the stale translations still carry
> the old renderings. Always translate with the consolidated glossary, then
> score.

### Step 4 — Stage 2: Translate (placeholder-token mode)  **[subagent: `TRANSLATION_MODEL`, parallel, one per chapter]**
Zero-drift enforcement: `enforce=yes` terms are injected as TOKENS, not spellings,
so the model literally cannot mis-spell them — code does the final substitution.
- **[harness]** `block, id_map = placeholder.render_glossary_placeholder(glossary)`
  splits the glossary into **fixed-token entities** (`강태광 | [[G1]]`) and
  **soft rendered terms** (`민주 | Minju | …`, the `enforce=no` ones). Assemble
  the prompt: `load_system_prompt(HONORIFICS)` + `block` + `build_user_message(
  TranslationContext(chapter_summaries=<prior window>), chapter_text)`.
- **[subagent]** each Opus agent emits the three sections, writing the token
  `[[Gn]]` verbatim wherever an enforce entity occurs (inflection outside the
  token). Writes raw reply to `WORK_DIR/trans/chNNN.txt`. Fully parallel.
- **[harness]** `parse_translation_output`, then
  `text, leaked = placeholder.apply_tokens(translation, id_map)` substitutes
  every token with its canonical English. `leaked` must be empty.

### Step 4b — Verify + repair token defects  **[harness] + [subagent: `REPAIR_MODEL`]**
`post-translate` detects TWO token-defect classes per chapter (both free,
deterministic) and records counts to `WORK_DIR/defects.json`:
- **forget-to-tokenize** — `find_untokenized_enforce_terms`: an enforce term
  whose Korean occurs but whose token is absent (spelled inline instead).
- **invalid / hallucinated** — `find_invalid_tokens`: a `[[G<id>]]` whose id is
  out of range (no such glossary entry) → would leak raw into the output.
  (In-range stray tokens for *soft* terms are not defects — they resolve.)
It prints `REPAIR_NEEDED: <stems>` and `DEFECTS forget=<n> invalid=<m>`.
**Only chapters with a defect invoke a model.**
- **[subagent: Sonnet]** `prompts/repair.md` handles both: re-insert tokens for
  missed entities; for invalid tokens, infer the intended entity from context +
  the `<valid_token_glossary>` and replace with the correct token (or plain
  English if it is no glossary entity). Surgical — changes nothing else.
- **[harness]** `repair_within_bounds` rejects collateral rewrites; re-detect
  both classes to confirm zero (cap 1–2 passes, then the gate flags it).

### Step 5 — Score + Assemble (FAIL-CLOSED)  **[harness] + [orchestrator]**
- **[harness]** `apply_tokens` each chapter, then `check_adherence`. **A chapter
  that still contains a raw token after repair is WITHHELD** — its body is
  replaced with a `>>> CHAPTER N WITHHELD … needs human review <<<` marker so
  the deliverable never ships a raw token. Any withheld chapter sets the run
  `status=NEEDS_HUMAN` and the output file is named `…_EN_INCOMPLETE.txt`.
- The `RESULT` line and `<slug>_report.json` carry: `status`, adherence %,
  `residual_leaks`, `withheld_chapters`, and **per-novel + per-chapter defect
  counts** (`forget_to_tokenize`, `invalid_token`).
- **[orchestrator]** the assembled file (`OUT_DIR/<NOVEL_SLUG>_ch001-0NN_EN.txt`)
  plus `glossary.json`, `summaries.json`, `defects.json`, and the report are the
  artifacts.

---

## Validation report (always produce)

| Check | How | Bar |
|---|---|---|
| **Glossary adherence** | `adherence.check_adherence` per chapter (harness). | ≥ 92% (enforce terms ≈ 100% by construction) |
| **Token leaks** | `apply_tokens` returns empty `leaked` for every chapter. | 0 |
| **Forget-to-tokenize residual** | `find_untokenized_enforce_terms` empty after Step 4b. | 0 (else flag) |
| **Parse success** | `parsing.parse_*` accepts each agent reply (harness). | 100% (retry once on failure, then flag) |
| **Markup integrity** | Per chapter, counts of `@it[`, `@b<`, `@b(N)@` match source vs translation. | Equal |
| **Continuity** | Names/terms consistent across chapters; summaries chain sensibly. | Manual spot-check |

Report violations by term with counts (which terms missed, in which chapters).

---

## Cost / accounting
Runs entirely on the Claude subscription via subagents — **zero API credit.**
Opus translation over many chapters is subscription-token-heavy; that is the
deliberate tradeoff for premium quality in a validation run.

---

## Confirmed defaults (2026-06-22, Example-Novel run)
- CHAPTER_COUNT = 10
- MINING_MODEL = sonnet, TRANSLATION_MODEL = opus
- HONORIFICS = keep
- Batch summary flow as described above (Stage-1 Sonnet summaries feed
  continuity; Opus writes the canonical final summary)
- SOURCE = `{user_provide_via_prompt}`
