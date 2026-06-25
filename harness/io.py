"""Loading and validation of chapter, glossary, and context inputs."""

from __future__ import annotations

import json
from pathlib import Path

from harness.models import ChapterSummary, GlossaryEntry, TranslationContext


class InputError(Exception):
    pass


def load_chapter(path: Path) -> str:
    if not path.is_file():
        raise InputError(f"Chapter file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise InputError(f"Chapter file is empty: {path}")
    return text


def load_glossary(path: Path | None) -> tuple[GlossaryEntry, ...]:
    """Glossary JSON: a list of {korean, english, category, note?} objects,
    in append order."""
    if path is None:
        return ()
    if not path.is_file():
        raise InputError(f"Glossary file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return tuple(
            GlossaryEntry(
                korean=e["korean"],
                english=e["english"],
                category=e["category"],
                note=e.get("note", ""),
                enforce=e.get("enforce", True),
            )
            for e in data
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise InputError(f"Invalid glossary file {path}: {exc}") from exc


def load_context(glossary_path: Path | None, summaries_path: Path | None) -> TranslationContext:
    """Summaries JSON: {"arc_summary": str, "chapter_summaries":
    [{"chapter": int, "summary": str}, ...]}."""
    glossary = load_glossary(glossary_path)
    if summaries_path is None:
        return TranslationContext(glossary=glossary)
    if not summaries_path.is_file():
        raise InputError(f"Summaries file not found: {summaries_path}")
    try:
        data = json.loads(summaries_path.read_text(encoding="utf-8"))
        summaries = tuple(
            ChapterSummary(chapter=int(s["chapter"]), summary=str(s["summary"]))
            for s in data.get("chapter_summaries", [])
        )
        return TranslationContext(
            glossary=glossary,
            arc_summary=str(data.get("arc_summary", "")),
            chapter_summaries=summaries,
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise InputError(f"Invalid summaries file {summaries_path}: {exc}") from exc
