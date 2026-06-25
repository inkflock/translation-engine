"""Tests for glossary merge/append logic (U5)."""

import pytest

from harness.glossary import append_new_terms, merge_mined_terms
from harness.models import GlossaryEntry
from harness.parsing import ParseError, parse_arc_summary

A1 = GlossaryEntry("소목단", "So Mok-dan", "person", "from ch1")
A2 = GlossaryEntry("소목단", "So Mokdan", "person", "from ch2, different rendering")
B = GlossaryEntry("숙적한", "Suk Jeok-han", "person", "")
C = GlossaryEntry("북라 부락", "Bukra Tribe", "place", "")


def test_merge_keeps_earliest_chapter_rendering():
    merged = merge_mined_terms([(2, (A2, B)), (1, (A1,))])
    assert merged == (A1, B)


def test_merge_preserves_chapter_then_position_order():
    merged = merge_mined_terms([(1, (A1, C)), (2, (B,))])
    assert merged == (A1, C, B)


def test_append_drops_established_terms_and_dedupes_batch():
    glossary = (A1,)
    updated = append_new_terms(glossary, (A2, B, B, C))
    assert updated == (A1, B, C)
    assert glossary == (A1,)  # original untouched


def test_clean_indecisive_rendering_takes_first_alternative():
    from harness.glossary import clean_mined_terms

    slashed = GlossaryEntry("부락", "settlement/tribe", "place", "")
    parens = GlossaryEntry("무의", "Shaman (or Witch)", "rank_title", "")
    fine = GlossaryEntry("소목단", "So Mok-dan", "person", "")
    cleaned, fixed = clean_mined_terms((slashed, parens, fine))
    assert cleaned[0].english == "settlement"
    assert cleaned[1].english == "Shaman"
    assert cleaned[2] is fine
    assert fixed == 2


def test_parse_arc_summary():
    assert parse_arc_summary("<story_so_far>\nThe story.\n</story_so_far>") == "The story."
    with pytest.raises(ParseError):
        parse_arc_summary("no section")
