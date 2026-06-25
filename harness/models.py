"""Core immutable data types shared across the harness."""

from __future__ import annotations

from dataclasses import dataclass

GLOSSARY_CATEGORIES = (
    "person",
    "place",
    "organization",
    "technique",
    "rank_title",
    "item",
    "creature",
    "other",
)


@dataclass(frozen=True)
class GlossaryEntry:
    korean: str
    english: str
    category: str
    note: str = ""
    enforce: bool = True
    """Hard-enforce this rendering via the placeholder protocol. False for
    ambiguous/homonym/common-noun terms that must stay context-dependent
    (e.g. 민주, which is also the word 'democratization')."""

    def __post_init__(self) -> None:
        if not self.korean.strip():
            raise ValueError("GlossaryEntry.korean must be non-empty")
        if not self.english.strip():
            raise ValueError(f"GlossaryEntry.english must be non-empty (term: {self.korean!r})")
        if self.category not in GLOSSARY_CATEGORIES:
            raise ValueError(
                f"Unknown glossary category {self.category!r} for term {self.korean!r}; "
                f"expected one of {GLOSSARY_CATEGORIES}"
            )


@dataclass(frozen=True)
class ChapterSummary:
    chapter: int
    summary: str


@dataclass(frozen=True)
class TranslationContext:
    """Everything besides the chapter text that goes into one translation call."""

    glossary: tuple[GlossaryEntry, ...] = ()
    arc_summary: str = ""
    chapter_summaries: tuple[ChapterSummary, ...] = ()


@dataclass(frozen=True)
class TranslationResult:
    translation: str
    new_terms: tuple[GlossaryEntry, ...]
    summary: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
