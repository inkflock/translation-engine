"""Parse the model's three-section output into a TranslationResult.

Parse strictness is deliberate: parse-failure rate is a measured outcome of
the format experiments (plan unit U3), so malformed output raises instead of
being silently repaired.
"""

from __future__ import annotations

import json
import re

from harness.models import GlossaryEntry, TranslationResult


class ParseError(Exception):
    pass


def _extract_section(raw: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", raw, re.DOTALL)
    return match.group(1).strip() if match else None


def parse_term_line(line: str) -> GlossaryEntry:
    fields = [f.strip() for f in line.split("|")]
    if len(fields) < 3:
        raise ParseError(f"Malformed glossary term line (need `ko | en | category [| note [| enforce]]`): {line!r}")
    note = fields[3] if len(fields) > 3 else ""
    enforce = True
    if len(fields) > 4 and fields[4]:
        enforce = fields[4].strip().lower() not in ("no", "false", "0", "soft")
    try:
        return GlossaryEntry(
            korean=fields[0], english=fields[1], category=fields[2], note=note, enforce=enforce
        )
    except ValueError as exc:
        raise ParseError(f"Invalid glossary term line {line!r}: {exc}") from exc


def parse_translation_output(raw: str) -> TranslationResult:
    translation = _extract_section(raw, "translation")
    if not translation:
        raise ParseError("Output is missing a non-empty <translation> section")
    summary = _extract_section(raw, "chapter_summary")
    if not summary:
        raise ParseError("Output is missing a non-empty <chapter_summary> section")

    terms_block = _extract_section(raw, "new_glossary_terms")
    if terms_block is None:
        raise ParseError("Output is missing the <new_glossary_terms> section")

    return TranslationResult(
        translation=translation, new_terms=_parse_terms_block(terms_block), summary=summary
    )


def _parse_terms_block(terms_block: str) -> tuple[GlossaryEntry, ...]:
    stripped = terms_block.strip()
    # Tolerate `NONE` with trailing commentary (seen live), but only when no
    # term lines follow — never silently drop reported terms.
    if stripped.upper().startswith("NONE") and "|" not in stripped:
        return ()
    new_terms: list[GlossaryEntry] = []
    for line in stripped.splitlines():
        line = line.strip().strip("`")
        if line and line.upper() != "NONE":
            new_terms.append(parse_term_line(line))
    return tuple(new_terms)


def parse_translation_only(raw: str) -> str:
    """Parse the output of a translation-only call (U3 split-call variant)."""
    translation = _extract_section(raw, "translation")
    if not translation:
        raise ParseError("Output is missing a non-empty <translation> section")
    return translation


def parse_extraction_output(raw: str) -> tuple[tuple[GlossaryEntry, ...], str]:
    """Parse the output of an extraction-only call (U3 split-call variant)."""
    summary = _extract_section(raw, "chapter_summary")
    if not summary:
        raise ParseError("Output is missing a non-empty <chapter_summary> section")
    terms_block = _extract_section(raw, "new_glossary_terms")
    if terms_block is None:
        raise ParseError("Output is missing the <new_glossary_terms> section")
    return _parse_terms_block(terms_block), summary


def parse_arc_summary(raw: str) -> str:
    """Parse the arc-summary regeneration output (story-so-far compression)."""
    summary = _extract_section(raw, "story_so_far")
    if not summary:
        raise ParseError("Output is missing a non-empty <story_so_far> section")
    return summary


JUDGE_DIMENSIONS = ("accuracy", "naturalness", "voice", "terminology", "formatting")

_VERDICT_RE = re.compile(r"\b(A|B|tie)\b", re.IGNORECASE)


def _verdict(text: str) -> str:
    match = _VERDICT_RE.search(text)
    if not match:
        raise ParseError(f"No A/B/tie verdict found in: {text!r}")
    return match.group(1).upper() if match.group(1).lower() != "tie" else "tie"


def parse_judge_output(raw: str) -> dict:
    """Parse the U4 pairwise judge output.

    Returns {"overall": "A"|"B"|"tie", "rationale": str, "dimensions": {name: verdict}}.
    Dimension sections are parsed leniently (a missing one becomes "?"); the
    overall verdict is required.
    """
    overall_section = _extract_section(raw, "overall_winner")
    if not overall_section:
        raise ParseError("Judge output is missing a non-empty <overall_winner> section")
    dimensions = {}
    for dim in JUDGE_DIMENSIONS:
        section = _extract_section(raw, dim)
        try:
            dimensions[dim] = _verdict(section) if section else "?"
        except ParseError:
            dimensions[dim] = "?"
    return {
        "overall": _verdict(overall_section),
        "rationale": _extract_section(raw, "rationale") or "",
        "dimensions": dimensions,
    }


def parse_translation_output_json(raw: str) -> TranslationResult:
    """Parse the JSON output variant (U3 format experiment).

    Accepts an optional markdown code fence around the object, since that is
    a failure mode we want to tolerate when measuring the harder ones.
    """
    text = raw.strip()
    fence = re.match(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ParseError(f"Expected a JSON object, got {type(data).__name__}")

    missing = {"translation", "new_glossary_terms", "chapter_summary"} - data.keys()
    if missing:
        raise ParseError(f"JSON output is missing keys: {sorted(missing)}")
    translation = data["translation"]
    summary = data["chapter_summary"]
    raw_terms = data["new_glossary_terms"]
    if not isinstance(translation, str) or not translation.strip():
        raise ParseError("JSON 'translation' must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ParseError("JSON 'chapter_summary' must be a non-empty string")
    if not isinstance(raw_terms, list):
        raise ParseError("JSON 'new_glossary_terms' must be a list")

    new_terms: list[GlossaryEntry] = []
    for item in raw_terms:
        if not isinstance(item, dict):
            raise ParseError(f"Glossary term must be an object, got: {item!r}")
        try:
            new_terms.append(
                GlossaryEntry(
                    korean=item.get("korean", ""),
                    english=item.get("english", ""),
                    category=item.get("category", ""),
                    note=item.get("note", "") or "",
                )
            )
        except ValueError as exc:
            raise ParseError(f"Invalid glossary term {item!r}: {exc}") from exc

    return TranslationResult(
        translation=translation.strip(), new_terms=tuple(new_terms), summary=summary.strip()
    )
