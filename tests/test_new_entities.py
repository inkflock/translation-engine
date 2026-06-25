"""Tests for (b): emission-time referent tagging via [[NEW:korean|english]]."""

from harness.models import GlossaryEntry
from harness.placeholder import (
    apply_tokens,
    find_new_entity_tokens,
    fold_glossary_entries,
    fold_new_entities,
)


def test_find_new_entity_tokens_with_rendering():
    text = "The [[NEW:백호상단|Baekho Trading]] men attacked at dawn."
    assert find_new_entity_tokens(text) == [("백호상단", "Baekho Trading")]


def test_find_new_entity_tokens_missing_rendering():
    assert find_new_entity_tokens("[[NEW:백호상단]] arrived.") == [("백호상단", "")]


def test_apply_tokens_resolves_new_with_rendering():
    out, leaked = apply_tokens("[[NEW:백호상단|Baekho Trading]]'s men", {})
    assert out == "Baekho Trading's men"
    assert leaked == []


def test_apply_tokens_flags_new_without_rendering():
    out, leaked = apply_tokens("[[NEW:백호상단]] arrived", {})
    assert leaked == ["[[NEW:백호상단]]"]
    assert "[[NEW:백호상단]]" in out  # left intact for resolution


def test_apply_tokens_normalizes_extra_brackets_around_token():
    out, leaked = apply_tokens("the [[[G1]] scored", {1: "Drogba"})
    assert out == "the Drogba scored"
    assert leaked == []


def test_apply_tokens_strips_malformed_plain_brackets():
    # model over-bracketed a rendered term -> strip to inner text, not a leak
    out, leaked = apply_tokens("his [[red eye]] and [[Beginner's Luck]]", {})
    assert out == "his red eye and Beginner's Luck"
    assert leaked == []


def test_apply_tokens_does_not_strip_unresolved_new_or_out_of_range():
    out, leaked = apply_tokens("[[NEW:백호상단]] and [[G99]]", {1: "x"})
    assert "[[NEW:백호상단]]" in out and "[[G99]]" in out
    assert set(leaked) == {"[[NEW:백호상단]]", "[[G99]]"}


def test_apply_tokens_handles_glossary_and_new_together():
    out, leaked = apply_tokens(
        "[[G1]] met [[NEW:백호상단|Baekho Trading]].", {1: "Gang Tae-gwang"}
    )
    assert out == "Gang Tae-gwang met Baekho Trading."
    assert leaked == []


def test_apply_tokens_recovers_model_invented_hybrid_token():
    # swiftblade: the model invented `[[G<n>:korean|english]]` (a mash-up of the
    # numbered + NEW syntaxes). It carries its own rendering, so recover it.
    out, leaked = apply_tokens(
        "The [[G134:무림맹|Murim Alliance]] gathered.", {}
    )
    assert out == "The Murim Alliance gathered."
    assert leaked == []


def test_apply_tokens_failclosed_catches_unknown_bracket_format():
    # An invented format that carries NO recoverable english must NOT slip past
    # the gate just because it matches none of the known token regexes.
    out, leaked = apply_tokens("A raw [[G134:무림맹]] token.", {})
    assert "[[G134:무림맹]]" in out          # left raw (unrecoverable)
    assert leaked == ["[[G134:무림맹]]"]      # but reported so the gate withholds


def test_fold_new_entities_appends_deduped_preserving_existing_ids():
    glossary = (GlossaryEntry("강태광", "Gang Tae-gwang", "person", "", enforce=True),)
    new = [("백호상단", "Baekho Trading"), ("백호상단", "Baekho Trading"),  # dup
           ("강태광", "Kang"),  # already present -> skip
           ("천수관음", "Thousand-Hand Goddess")]
    folded, added = fold_new_entities(glossary, new)
    assert [e.korean for e in folded] == ["강태광", "백호상단", "천수관음"]
    assert folded[0] is glossary[0]              # existing id 1 unchanged
    assert all(e.enforce for e in added)         # auto-added are enforce=yes
    assert [e.korean for e in added] == ["백호상단", "천수관음"]


def test_fold_new_entities_skips_entries_without_rendering():
    folded, added = fold_new_entities((), [("백호상단", "")])
    assert added == []  # no english -> cannot fold, needs resolution


def test_fold_glossary_entries_dedups_and_preserves_existing():
    glossary = (GlossaryEntry("강태광", "Gang Tae-gwang", "person", "", enforce=True),)
    reported = [
        GlossaryEntry("종로", "Jongno", "place", "from ch12"),
        GlossaryEntry("종로", "Jongno", "place", ""),          # cross-chapter dup
        GlossaryEntry("강태광", "Kang", "person", ""),          # already present -> skip
    ]
    folded, added = fold_glossary_entries(glossary, reported)
    assert [e.korean for e in added] == ["종로"]
    assert folded[0] is glossary[0]                              # existing untouched
    assert folded[-1].english == "Jongno"
