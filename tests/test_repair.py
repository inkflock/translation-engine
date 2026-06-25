"""Tests for forget-to-tokenize detection + repair diff-guard."""

from harness.models import GlossaryEntry
from harness.placeholder import (
    find_invalid_tokens,
    find_untokenized_enforce_terms,
    repair_within_bounds,
)

G = (
    GlossaryEntry("강태광", "Gang Tae-gwang", "person", "", enforce=True),      # id 1
    GlossaryEntry("다나을 요양병원", "Danaul Nursing Hospital", "place", "", enforce=True),  # id 2
    GlossaryEntry("민주", "Minju", "person", "", enforce=False),               # id 3 (soft)
)
SRC = "강태광은 다나을 요양병원에 갔다. 민주도 거기 있었다."


def test_detects_enforce_term_whose_token_is_absent():
    # ch tokenised 강태광 ([[G1]]) but spelled the hospital inline
    translation = "[[G1]] went to the Danaeul Care Hospital. Minju was there too."
    missed = find_untokenized_enforce_terms(SRC, translation, G)
    assert [e.korean for e, _ in missed] == ["다나을 요양병원"]
    assert missed[0][1] == "[[G2]]"


def test_no_residual_when_all_enforce_tokens_present():
    translation = "[[G1]] went to [[G2]]. Minju was there too."
    assert find_untokenized_enforce_terms(SRC, translation, G) == []


def test_soft_term_never_flagged():
    # 민주 is soft; even though spelled out, it is not a residual
    translation = "[[G1]] went to [[G2]]. Minju was there too."
    missed = find_untokenized_enforce_terms(SRC, translation, G)
    assert all(e.korean != "민주" for e, _ in missed)


def test_enforce_term_absent_from_source_not_flagged():
    translation = "[[G1]] went somewhere."  # hospital + 민주 not in this source
    src = "강태광은 집에 갔다."
    assert find_untokenized_enforce_terms(src, translation, G) == []


def test_find_invalid_tokens_flags_out_of_range():
    # glossary has 3 positions; [[G5]] is fully hallucinated
    text = "[[G1]] met [[G3]] near [[G5]] and again [[G5]]."
    invalid = find_invalid_tokens(text, G)
    assert invalid == ["[[G5]]", "[[G5]]"]  # both occurrences, in order


def test_find_invalid_tokens_empty_when_all_in_range():
    assert find_invalid_tokens("[[G1]] and [[G3]] only.", G) == []


def test_diff_guard_accepts_minimal_edit():
    original = "He went to a care hospital and waited for hours in the lobby."
    repaired = "He went to [[G2]] and waited for hours in the lobby."
    assert repair_within_bounds(original, repaired) is True


def test_diff_guard_rejects_wholesale_rewrite():
    original = "He went to a care hospital and waited for hours in the lobby."
    repaired = "A completely different sentence with new unrelated content here now."
    assert repair_within_bounds(original, repaired) is False


def test_diff_guard_accepts_dense_retokenisation():
    # Same prose, but many scattered proper-noun mentions converted to tokens —
    # character-level ratio falls below 0.70, yet nothing about the prose changed.
    # Regression for the swiftblade ch14 false-rejection.
    original = (
        "Bi-yeong of the Jeomchang Sect drew his blade. Bi-yeong was fast; the "
        "Jeomchang Sect elders watched as Bi-yeong cut down the Cheonma envoy. "
        "Even the Cheonma feared Bi-yeong and the Jeomchang Sect that day."
    )
    repaired = (
        "[[G1]] of the [[G4]] drew his blade. [[G1]] was fast; the "
        "[[G4]] elders watched as [[G1]] cut down the [[G7]] envoy. "
        "Even the [[G7]] feared [[G1]] and the [[G4]] that day."
    )
    assert repair_within_bounds(original, repaired) is True


def test_diff_guard_still_rejects_rewrite_even_with_tokens():
    # Tokens present but the surrounding prose was genuinely rewritten → reject.
    original = "He went to a care hospital and waited for hours in the lobby."
    repaired = "[[G2]] is where an entirely new and unrelated story now unfolds here."
    assert repair_within_bounds(original, repaired) is False


# --- forget-detector superset masking (scoundrel false-positive) -----------

GS = (
    GlossaryEntry("아스테르", "Aster", "organization", "", enforce=True),                  # id 1
    GlossaryEntry("아스테르 엔터테인먼트", "Aster Entertainment", "organization", "", enforce=True),  # id 2
)


def test_short_key_not_flagged_when_only_inside_longer_term():
    # Source only ever has the LONG term; the translator correctly emitted [[G2]].
    # The short key 아스테르 must NOT be independently demanded as a forget.
    src = "아스테르 엔터테인먼트의 사옥은 강남에 있다."
    translation = "[[G2]]'s building is in Gangnam."
    missed = find_untokenized_enforce_terms(src, translation, GS)
    assert missed == []


def test_short_key_still_flagged_when_it_stands_alone():
    # Here 아스테르 appears on its own (not part of the longer term) and was
    # spelled inline → it is a genuine forget.
    src = "아스테르는 거대 기획사다. 아스테르 엔터테인먼트는 그 자회사다."
    translation = "Aster is a giant agency. [[G2]] is its subsidiary."
    missed = find_untokenized_enforce_terms(src, translation, GS)
    assert [e.korean for e, _ in missed] == ["아스테르"]
