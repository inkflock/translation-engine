import pytest

from harness.parsing import ParseError, parse_translation_output

WELL_FORMED = """
<translation>
Kim Cheol-su stepped through the gates of the Azure Dragon Sect.
</translation>

<new_glossary_terms>
장로 회의 | Council of Elders | organization | sect governing body
흑풍대 | Black Wind Squad | organization
</new_glossary_terms>

<chapter_summary>
Cheol-su enters the sect and is summoned before the Council of Elders.
</chapter_summary>
"""


def test_well_formed_output_parses_into_three_parts():
    result = parse_translation_output(WELL_FORMED)
    assert result.translation.startswith("Kim Cheol-su stepped")
    assert len(result.new_terms) == 2
    assert result.new_terms[0].english == "Council of Elders"
    assert result.new_terms[1].note == ""
    assert result.summary.startswith("Cheol-su enters")


def test_none_terms_yield_empty_list():
    raw = WELL_FORMED.replace(
        "장로 회의 | Council of Elders | organization | sect governing body\n흑풍대 | Black Wind Squad | organization",
        "NONE",
    )
    assert parse_translation_output(raw).new_terms == ()


def test_none_with_commentary_yields_empty_list():
    # Seen live in U5: the model wrote `NONE (additional terms are ...)`.
    raw = WELL_FORMED.replace(
        "장로 회의 | Council of Elders | organization | sect governing body\n흑풍대 | Black Wind Squad | organization",
        "NONE (additional terms are either common nouns or handled by existing glossary)",
    )
    assert parse_translation_output(raw).new_terms == ()


def test_none_followed_by_term_lines_still_parses_terms():
    raw = WELL_FORMED.replace(
        "장로 회의 | Council of Elders | organization | sect governing body\n흑풍대 | Black Wind Squad | organization",
        "NONE\n흑풍대 | Black Wind Squad | organization",
    )
    assert len(parse_translation_output(raw).new_terms) == 1


def test_missing_translation_section_raises():
    raw = WELL_FORMED.replace("<translation>", "").replace("</translation>", "")
    with pytest.raises(ParseError, match="<translation>"):
        parse_translation_output(raw)


def test_missing_summary_section_raises():
    raw = WELL_FORMED.replace("chapter_summary>", "different_tag>")
    with pytest.raises(ParseError, match="<chapter_summary>"):
        parse_translation_output(raw)


def test_malformed_term_line_raises_with_line_content():
    raw = WELL_FORMED.replace(
        "흑풍대 | Black Wind Squad | organization", "흑풍대 Black Wind Squad"
    )
    with pytest.raises(ParseError, match="흑풍대 Black Wind Squad"):
        parse_translation_output(raw)


def test_unknown_category_raises():
    raw = WELL_FORMED.replace("| organization |", "| faction |")
    with pytest.raises(ParseError, match="faction"):
        parse_translation_output(raw)
