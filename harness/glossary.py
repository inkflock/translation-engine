"""Glossary merging for the two-stage backlog pipeline (Stage-1 normalization).

Chapters are mined in parallel, so the same Korean term may be proposed by
several chapters with different renderings. Normalization keeps the rendering
from the earliest chapter (stable, deterministic) and drops later duplicates.
"""

from __future__ import annotations

import re
from collections import Counter

from harness.models import GlossaryEntry

_PAREN = re.compile(r"\([^)]*\)|（[^）]*）")


def normalize_korean_key(korean: str) -> str:
    """Canonical key for deduping mined terms.

    Parallel mining yields spacing/annotation variants of the same Korean
    term (`데스 나이트 (데스나이트)` vs `데스나이트`, `검수림(劍樹林)` vs `검수림`).
    Strip parenthetical glosses (Hangul or Hanja) and all whitespace so the
    variants collapse to one key.
    """
    return re.sub(r"\s+", "", _PAREN.sub("", korean))


def clean_mined_terms(
    terms: tuple[GlossaryEntry, ...],
) -> tuple[tuple[GlossaryEntry, ...], int]:
    """Normalize indecisive mined renderings; returns (terms, fixed_count).

    Miners sometimes emit alternatives ("settlement/tribe", "Shaman (or
    Witch)") despite being told to pick one. A rendering with alternatives
    can never be matched verbatim, so take the first alternative. U6 showed
    these few defective entries account for most adherence violations.
    """
    cleaned: list[GlossaryEntry] = []
    fixed = 0
    for term in terms:
        english = term.english.split("/")[0].split("(")[0].strip()
        if english and english != term.english:
            cleaned.append(
                GlossaryEntry(term.korean, english, term.category, term.note)
            )
            fixed += 1
        else:
            cleaned.append(term)
    return tuple(cleaned), fixed


def merge_mined_terms(
    mined: list[tuple[int, tuple[GlossaryEntry, ...]]],
) -> tuple[GlossaryEntry, ...]:
    """Merge per-chapter mined terms into one canonical glossary.

    Terms are grouped by `normalize_korean_key` (so spacing/parenthetical
    variants collapse). Within a group the canonical English rendering is
    chosen by **majority vote**, ties broken by earliest chapter of
    appearance. The displayed Korean prefers the surface form equal to the
    normalized key, else the earliest-seen surface. Distinct keys are kept
    separate and ordered by first appearance — a compound like `검성 척준성`
    never folds into its part `검성`.
    """
    # group[key] = list of (chapter, appearance_index, term), in stream order
    groups: dict[str, list[tuple[int, int, GlossaryEntry]]] = {}
    order: list[str] = []
    appearance = 0
    for chapter, terms in sorted(mined, key=lambda pair: pair[0]):
        for term in terms:
            key = normalize_korean_key(term.korean)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((chapter, appearance, term))
            appearance += 1

    merged: list[GlossaryEntry] = []
    for key in order:
        members = groups[key]
        counts = Counter(m[2].english for m in members)
        top = max(counts.values())
        tied = {eng for eng, c in counts.items() if c == top}
        # earliest (chapter, appearance) among entries whose rendering is tied-top
        winner = min(
            (m for m in members if m[2].english in tied),
            key=lambda m: (m[0], m[1]),
        )[2]
        surface = next(
            (m[2].korean for m in members if m[2].korean == key),
            members[0][2].korean,
        )
        merged.append(
            GlossaryEntry(surface, winner.english, winner.category, winner.note)
        )
    return tuple(merged)


def append_new_terms(
    glossary: tuple[GlossaryEntry, ...], new_terms: tuple[GlossaryEntry, ...]
) -> tuple[GlossaryEntry, ...]:
    """Append-only glossary update for the incremental pipeline.

    Terms whose Korean form is already established are dropped — an existing
    rendering is never overwritten, keeping the cached prompt prefix stable.
    """
    seen = {entry.korean for entry in glossary}
    additions: list[GlossaryEntry] = []
    for term in new_terms:
        if term.korean not in seen:
            additions.append(term)
            seen.add(term.korean)
    return glossary + tuple(additions)
