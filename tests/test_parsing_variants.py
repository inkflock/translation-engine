"""Tests for U3 format-experiment parsers: JSON output, split-call outputs."""

import pytest

from harness.parsing import (
    ParseError,
    parse_extraction_output,
    parse_translation_only,
    parse_translation_output_json,
)

VALID_JSON = """
{
  "translation": "So Mok-dan woke up.",
  "new_glossary_terms": [
    {"korean": "소목단", "english": "So Mok-dan", "category": "person", "note": "protagonist"}
  ],
  "chapter_summary": "She transmigrates."
}
"""


def test_json_happy_path():
    result = parse_translation_output_json(VALID_JSON)
    assert result.translation == "So Mok-dan woke up."
    assert result.new_terms[0].korean == "소목단"
    assert result.summary == "She transmigrates."


def test_json_accepts_code_fences():
    fenced = f"```json\n{VALID_JSON.strip()}\n```"
    result = parse_translation_output_json(fenced)
    assert result.translation == "So Mok-dan woke up."


def test_json_empty_terms_list_ok():
    raw = '{"translation": "t", "new_glossary_terms": [], "chapter_summary": "s"}'
    assert parse_translation_output_json(raw).new_terms == ()


def test_json_invalid_syntax_raises():
    with pytest.raises(ParseError):
        parse_translation_output_json('{"translation": "unterminated')


def test_json_missing_key_raises():
    with pytest.raises(ParseError):
        parse_translation_output_json('{"translation": "t", "chapter_summary": "s"}')


def test_json_bad_category_raises():
    raw = (
        '{"translation": "t", "chapter_summary": "s", '
        '"new_glossary_terms": [{"korean": "k", "english": "e", "category": "bogus"}]}'
    )
    with pytest.raises(ParseError):
        parse_translation_output_json(raw)


def test_translation_only_happy_path():
    raw = "<translation>\nHello world.\n</translation>"
    assert parse_translation_only(raw) == "Hello world."


def test_translation_only_missing_raises():
    with pytest.raises(ParseError):
        parse_translation_only("no tags here")


def test_extraction_output_happy_path():
    raw = (
        "<new_glossary_terms>\n소목단 | So Mok-dan | person | protagonist\n</new_glossary_terms>\n"
        "<chapter_summary>\nShe transmigrates.\n</chapter_summary>"
    )
    terms, summary = parse_extraction_output(raw)
    assert terms[0].english == "So Mok-dan"
    assert summary == "She transmigrates."


def test_extraction_output_none_terms():
    raw = (
        "<new_glossary_terms>\nNONE\n</new_glossary_terms>\n"
        "<chapter_summary>\nSummary.\n</chapter_summary>"
    )
    terms, summary = parse_extraction_output(raw)
    assert terms == ()


def test_extraction_output_missing_summary_raises():
    with pytest.raises(ParseError):
        parse_extraction_output("<new_glossary_terms>\nNONE\n</new_glossary_terms>")
