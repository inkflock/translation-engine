"""Tests for enforce flag (#3) + placeholder protocol (#2)."""

from harness.models import GlossaryEntry
from harness.parsing import parse_term_line
from harness.placeholder import (
    render_glossary_placeholder,
    apply_tokens,
    token_for,
)


# --- enforce flag ---
def test_entry_enforce_defaults_true():
    assert GlossaryEntry("강태광", "Gang Tae-gwang", "person").enforce is True


def test_parse_term_line_reads_enforce_field():
    e = parse_term_line("민주 | Minju | person | a name | no")
    assert e.enforce is False
    assert e.note == "a name"


def test_parse_term_line_enforce_defaults_true_when_absent():
    assert parse_term_line("강태광 | Gang Tae-gwang | person | protagonist").enforce is True


# --- placeholder rendering ---
def test_render_splits_enforce_vs_soft():
    g = (
        GlossaryEntry("강태광", "Gang Tae-gwang", "person", "", enforce=True),
        GlossaryEntry("민주", "Minju", "person", "homonym", enforce=False),
    )
    text, id_map = render_glossary_placeholder(g)
    # Full position map (both enforce and soft) so stray tokens always resolve…
    assert id_map == {1: "Gang Tae-gwang", 2: "Minju"}
    # …but the PROMPT tokenises only the enforce term; soft stays plain.
    assert token_for(1) in text                      # token shown for enforce
    assert "강태광 | [[G1]]" in text
    assert token_for(2) not in text                  # soft term NOT shown as a token
    assert "민주 | Minju" in text                     # soft term rendered normally
    assert "Gang Tae-gwang" not in text              # enforce English never exposed


# --- token substitution / post-processing ---
def test_apply_tokens_substitutes_and_keeps_inflection():
    out, leaked = apply_tokens("[[G1]]'s frozen-food empire", {1: "Gang Tae-gwang"})
    assert out == "Gang Tae-gwang's frozen-food empire"
    assert leaked == []


def test_apply_tokens_tolerates_whitespace_and_case():
    out, _ = apply_tokens("[[ g1 ]] arrived", {1: "Gang Tae-gwang"})
    assert out == "Gang Tae-gwang arrived"


def test_apply_tokens_reports_leaked_unknown_token():
    out, leaked = apply_tokens("[[G9]] is unmapped", {1: "Gang Tae-gwang"})
    assert "[[G9]]" in out          # left intact
    assert leaked == ["[[G9]]"]


def test_render_then_apply_roundtrip():
    g = (GlossaryEntry("강태광", "Gang Tae-gwang", "person", "", enforce=True),)
    _, id_map = render_glossary_placeholder(g)
    out, leaked = apply_tokens("Then [[G1]] spoke.", id_map)
    assert out == "Then Gang Tae-gwang spoke."
    assert leaked == []
