"""Tests for the U4 judge-output parser."""

import pytest

from harness.parsing import ParseError, parse_judge_output

FULL = """
<accuracy>A — B drops a sentence in the flashback.</accuracy>
<naturalness>tie — both read naturally.</naturalness>
<voice>B — sharper dialogue register.</voice>
<terminology>A — consistent name renderings.</terminology>
<formatting>tie — both preserve breaks.</formatting>
<overall_winner>A</overall_winner>
<rationale>A is more faithful overall.</rationale>
"""


def test_full_judge_output():
    result = parse_judge_output(FULL)
    assert result["overall"] == "A"
    assert result["dimensions"]["accuracy"] == "A"
    assert result["dimensions"]["naturalness"] == "tie"
    assert result["dimensions"]["voice"] == "B"
    assert result["rationale"] == "A is more faithful overall."


def test_tie_overall_and_case_insensitive():
    raw = "<overall_winner>Tie</overall_winner><rationale>even</rationale>"
    assert parse_judge_output(raw)["overall"] == "tie"


def test_missing_overall_raises():
    with pytest.raises(ParseError):
        parse_judge_output("<accuracy>A</accuracy>")


def test_missing_dimensions_tolerated():
    raw = "<overall_winner>B</overall_winner>"
    result = parse_judge_output(raw)
    assert result["overall"] == "B"
    assert result["dimensions"]["voice"] == "?"
    assert result["rationale"] == ""
