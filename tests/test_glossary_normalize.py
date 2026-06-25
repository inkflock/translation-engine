"""Tests for glossary key-normalization + rendering reconciliation (fix #1)."""

from harness.glossary import normalize_korean_key, merge_mined_terms
from harness.models import GlossaryEntry


def test_normalize_strips_spaces_and_parentheticals():
    assert normalize_korean_key("데스 나이트 (데스나이트)") == "데스나이트"
    assert normalize_korean_key("데스나이트") == "데스나이트"
    assert normalize_korean_key("검수림(劍樹林)") == "검수림"
    assert normalize_korean_key("검수림") == "검수림"


def test_merge_collapses_spacing_and_paren_variants():
    a = GlossaryEntry("데스나이트", "Death Knight", "creature", "")
    b = GlossaryEntry("데스 나이트 (데스나이트)", "Death Knight", "creature", "from ch7")
    merged = merge_mined_terms([(6, (a,)), (7, (b,))])
    keys = [e.korean for e in merged]
    assert keys == ["데스나이트"]  # one entry, canonical surface form


def test_merge_reconciles_rendering_by_majority():
    # Same entity, three chapters: two say "Rokpia", one says "Rockpia".
    e1 = GlossaryEntry("록피아", "Rockpia", "place", "")
    e2 = GlossaryEntry("록피아", "Rokpia", "place", "")
    e3 = GlossaryEntry("록피아", "Rokpia", "place", "")
    merged = merge_mined_terms([(1, (e1,)), (2, (e2,)), (3, (e3,))])
    assert len(merged) == 1
    assert merged[0].english == "Rokpia"  # majority wins, not first


def test_merge_majority_tie_breaks_to_earliest_chapter():
    e1 = GlossaryEntry("모르그", "Morg", "place", "")
    e2 = GlossaryEntry("모르그", "Morge", "place", "")
    merged = merge_mined_terms([(1, (e1,)), (2, (e2,))])
    assert merged[0].english == "Morg"  # 1-1 tie -> earliest chapter


def test_merge_preserves_distinct_keys_and_order():
    a = GlossaryEntry("차하상", "Cha Ha-sang", "person", "")
    b = GlossaryEntry("홍무진", "Hong Mu-jin", "person", "")
    merged = merge_mined_terms([(1, (a, b))])
    assert [e.korean for e in merged] == ["차하상", "홍무진"]


def test_merge_does_not_fold_distinct_compound_into_its_part():
    # 검성 (title) and 검성 척준성 (person) are different entities; keep both.
    title = GlossaryEntry("검성", "Sword Saint", "rank_title", "")
    person = GlossaryEntry("검성 척준성", "Cheok Jun-seong the Sword Saint", "person", "")
    merged = merge_mined_terms([(1, (title, person))])
    assert len(merged) == 2
