"""Placeholder protocol — zero-drift enforcement of glossary renderings (#2).

A prompt-injected glossary is best-effort: the model sometimes overrides it
(e.g. spelling 강태광 as "Kang" instead of the canonical "Gang Tae-gwang").
To make drift *structurally impossible* for the terms that matter, the
translator is told to emit a sentinel TOKEN for each enforce term instead of
spelling it; this module renders that instruction and substitutes the tokens
with canonical English afterwards. Because the final spelling is done by code,
the model cannot drift it.

Only `enforce=True` entries are tokenised. Ambiguous/homonym terms
(`enforce=False`) stay in the prompt as normal rendered guidance (Tier B).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from harness.adherence import _korean_occurs
from harness.models import GlossaryEntry

# Tolerant of stray whitespace and case: [[G1]], [[ g1 ]], [[G01]].
TOKEN_RE = re.compile(r"\[\[\s*[Gg]\s*0*(\d+)\s*\]\]")

# Self-reported new entity: [[NEW:korean|English]] (english optional). The model
# emits this for a proper noun not in the fixed-token list, instead of inventing
# a token number — so the referent is recoverable deterministically (memo Case 1).
NEW_TOKEN_RE = re.compile(r"\[\[NEW:\s*([^|\]]+?)\s*(?:\|\s*([^\]]*?)\s*)?\]\]")


def find_new_entity_tokens(text: str) -> list[tuple[str, str]]:
    """Self-reported `[[NEW:korean|english]]` tokens as (korean, english).

    english is "" when the model omitted its rendering (needs resolution)."""
    return [(m.group(1).strip(), (m.group(2) or "").strip()) for m in NEW_TOKEN_RE.finditer(text)]


def token_for(index: int) -> str:
    return f"[[G{index}]]"


def render_glossary_placeholder(
    entries: tuple[GlossaryEntry, ...],
) -> tuple[str, dict[int, str]]:
    """Render the glossary prompt block in placeholder mode.

    Returns (block_text, id_to_english) where id_to_english maps each enforce
    token id to its canonical English (used by `apply_tokens`).

    The returned map covers EVERY glossary position — enforce and soft alike —
    so that a stray token the model invents for a soft term (it occasionally
    over-applies the pattern) still resolves instead of leaking. Only enforce
    terms are shown to the model as tokens in the prompt; soft terms appear as
    plain rendered guidance. Token ids are positional, so they stay stable as
    long as the glossary order is unchanged.
    """
    id_to_english: dict[int, str] = {}
    enforce_lines: list[str] = []
    soft_lines: list[str] = []
    for i, e in enumerate(entries, 1):
        id_to_english[i] = e.english  # full position map (both enforce and soft)
        if e.enforce:
            note = f"  ({e.note})" if e.note else ""
            enforce_lines.append(f"{e.korean} | {token_for(i)}{note}")
        else:
            soft_lines.append(f"{e.korean} | {e.english} | {e.category} | {e.note}".rstrip(" |"))

    parts = ["# Glossary — follow EXACTLY"]
    if enforce_lines:
        parts.append(
            "## Fixed-token entities\n"
            "When the Korean entity on the left appears in the chapter, output its "
            "TOKEN **exactly as shown** — never translate, romanize, or spell it "
            "yourself. Attach English inflection OUTSIDE the token "
            "(e.g. `[[G1]]'s`, `[[G1]]-led`). The token is replaced with the "
            "canonical name automatically.\n\n"
            "korean | token\n" + "\n".join(enforce_lines)
        )
    # Promoted above "rendered terms" and made mandatory with a hard trigger —
    # a vague "needs a consistent rendering" trigger got 0% adoption; "every
    # proper noun not listed" is followable.
    parts.append(
        "## MANDATORY — every OTHER proper noun becomes a [[NEW:…]] token\n"
        "For **every** proper noun that does NOT appear in the fixed-token list "
        "above — any character, place, organisation, group, brand, or named "
        "technique/item, **even one that appears only once** — you MUST write it "
        "in the translation as `[[NEW:<Korean source term>|<your English>]]`. "
        "Inflect outside the token (`[[NEW:백호상단|Baekho Trading]]'s`).\n"
        "- WRONG (spelled out): `Baekho Trading attacked.`\n"
        "- WRONG (invented number): `[[G999]] attacked.`\n"
        "- RIGHT: `[[NEW:백호상단|Baekho Trading]] attacked.`\n"
        "Rule of thumb: if you would list a term in your `<new_glossary_terms>` "
        "section, it MUST appear as a `[[NEW:…]]` token in the `<translation>` — "
        "the two must agree. **Never** write a `[[G<number>]]` that is not in the "
        "fixed list above; numbered tokens come only from that list."
    )
    if soft_lines:
        parts.append(
            "## Rendered terms (use this exact English; context-dependent)\n"
            "korean | english | category | note\n" + "\n".join(soft_lines)
        )
    return "\n\n".join(parts), id_to_english


def apply_tokens(text: str, id_to_english: dict[int, str]) -> tuple[str, list[str]]:
    """Replace `[[G<id>]]` tokens with canonical English.

    Returns (substituted_text, leaked). `leaked` is the FORMAT-AGNOSTIC set of
    anything still wrapped in `[[...]]` after every recovery pass — an
    out-of-range id, a renderless NEW token, or a token in some syntax the model
    invented that we could not recover. The fail-closed gate withholds on it, so
    a raw bracket can never reach a reader regardless of its shape.
    """
    # Tolerate accidental extra brackets around a numbered token (`[[[G4]]`).
    text = re.sub(r"\[{2,}(\s*[Gg]\s*0*\d+\s*)\]{2,}", r"[[\1]]", text)

    # In-range numbered tokens → canonical English (out-of-range left raw).
    text = TOKEN_RE.sub(lambda m: id_to_english.get(int(m.group(1)), m.group(0)), text)

    # Self-reported NEW entities with a rendering → that rendering.
    text = NEW_TOKEN_RE.sub(lambda m: (m.group(2) or "").strip() or m.group(0), text)

    # Model-invented labelled/hybrid tokens that still carry a rendering after the
    # pipe, e.g. `[[G134:무림맹|Murim Alliance]]` (a mash-up of the numbered and
    # NEW syntaxes seen in the wild). The english is recoverable, so unwrap it.
    text = re.sub(r"\[\[[^\[\]]*\|\s*([^\[\]|]+?)\s*\]\]", r"\1", text)

    # Strip leftover over-bracketing of plain/rendered terms — any `[[...]]` that
    # is NOT an (out-of-range) numbered token or an unresolved NEW token. The
    # inner text is the intended rendering, so unwrap it.
    text = re.sub(r"\[\[(?!NEW:)(?!\s*[Gg]\s*0*\d)([^\[\]]*?)\]\]", r"\1", text)

    # FAIL-CLOSED backstop: whatever is STILL bracketed is an unrecovered raw
    # token in some form. Report every occurrence so the gate withholds it.
    leaked = re.findall(r"\[\[[^\]]*\]\]", text)

    return text, leaked


def fold_new_entities(
    glossary: tuple[GlossaryEntry, ...], new_entities: list[tuple[str, str]]
) -> tuple[tuple[GlossaryEntry, ...], list[GlossaryEntry]]:
    """Append self-reported new entities to the glossary (deterministic fold-back).

    Dedupes by Korean, skips terms already present and any with no English
    rendering. Appends at the END so existing token ids stay stable. Returns
    (updated_glossary, added). Auto-added entries are enforce=yes."""
    seen = {e.korean for e in glossary}
    added: list[GlossaryEntry] = []
    for korean, english in new_entities:
        korean, english = korean.strip(), english.strip()
        if not korean or not english or korean in seen:
            continue
        added.append(GlossaryEntry(korean, english, "other",
                                   "auto-added from [[NEW]] self-report", enforce=True))
        seen.add(korean)
    return glossary + tuple(added), added


def fold_glossary_entries(
    glossary: tuple[GlossaryEntry, ...], entries: list[GlossaryEntry]
) -> tuple[tuple[GlossaryEntry, ...], list[GlossaryEntry]]:
    """Append already-parsed glossary entries (e.g. the model's reported
    `<new_glossary_terms>`) that aren't already present. Dedupes by Korean,
    preserves each entry's own category/note/enforce, appends at the end so
    existing token ids stay stable. Returns (updated_glossary, added)."""
    seen = {e.korean for e in glossary}
    added: list[GlossaryEntry] = []
    for e in entries:
        if e.korean.strip() and e.english.strip() and e.korean not in seen:
            added.append(e)
            seen.add(e.korean)
    return glossary + tuple(added), added


def find_untokenized_enforce_terms(
    source: str, translation_raw: str, glossary: tuple[GlossaryEntry, ...]
) -> list[tuple[GlossaryEntry, str]]:
    """Detect the forget-to-tokenize residual (deterministic, no model).

    Returns (entry, token) for every `enforce=True` term whose Korean occurs in
    the source chapter but whose token never appears in the raw translation —
    i.e. the translator spelled it inline instead of emitting its token.
    """
    present_ids = {int(m.group(1)) for m in TOKEN_RE.finditer(translation_raw)}
    keys = [e.korean for e in glossary]
    missed: list[tuple[GlossaryEntry, str]] = []
    for i, e in enumerate(glossary, 1):
        if not (e.enforce and i not in present_ids):
            continue
        # Superset masking: a short key that is a substring of a longer, separately
        # glossed term (e.g. 아스테르 inside 아스테르 엔터테인먼트) reads as
        # "standalone" at the word boundary. Strip every superset term's
        # occurrences first; only a TRULY independent mention then survives.
        masked = source
        for sup in (k for k in keys if k != e.korean and e.korean in k):
            masked = masked.replace(sup, "")
        if _korean_occurs(e.korean, masked):
            missed.append((e, token_for(i)))
    return missed


def find_invalid_tokens(text: str, glossary: tuple[GlossaryEntry, ...]) -> list[str]:
    """Token strings whose id is NOT a valid glossary position (1..N).

    These are fully hallucinated tokens — there is no entity to resolve them to,
    so `apply_tokens` would leave them raw in the output. They must be routed to
    repair (or fail the chapter closed). Returns every occurrence, in order.
    """
    n = len(glossary)
    return [m.group(0) for m in TOKEN_RE.finditer(text) if not (1 <= int(m.group(1)) <= n)]


def _prose_only(text: str) -> str:
    """Text with all `[[...]]` tokens removed, so a pure re-tokenization compares
    as unchanged and only genuine prose edits move the similarity ratio."""
    return re.sub(r"\[\[[^\]]*\]\]", "", text)


def repair_within_bounds(original: str, repaired: str, min_ratio: float = 0.7) -> bool:
    """Coarse guard against collateral damage: reject a repair that rewrote the
    prose wholesale. This is a safety net only — the authoritative check is
    re-running `find_untokenized_enforce_terms` after a repair.

    The comparison strips `[[...]]` tokens from both sides first. A clean repair
    only swaps proper nouns for tokens; on a name-dense chapter those scattered
    edits tank a raw character ratio (swiftblade ch14 hit 0.42) even though the
    prose is untouched. Stripping tokens makes pure re-tokenization compare ~1.0,
    while a real paraphrase or dropped passage still drops the ratio and is
    rejected.
    """
    return SequenceMatcher(None, _prose_only(original), _prose_only(repaired)).ratio() >= min_ratio
