"""Tests for the glossary adherence checker used by the U3 load experiment."""

from harness.adherence import check_adherence, terms_in_source
from harness.models import GlossaryEntry

SO_MOKDAN = GlossaryEntry("소목단", "So Mok-dan", "person", "protagonist")
SUK_JEOKHAN = GlossaryEntry("숙적한", "Suk Jeok-han", "person", "husband")
ABSENT = GlossaryEntry("백리한", "Baekri Han", "person", "not in chapter")
BEAST_HUSBAND = GlossaryEntry("수부", "beast-husband", "rank_title", "")

SOURCE = "소목단은 숙적한을 바라보았다. 그녀의 수부였다."


def test_terms_in_source_finds_only_present_terms():
    present = terms_in_source(SOURCE, (SO_MOKDAN, SUK_JEOKHAN, ABSENT, BEAST_HUSBAND))
    assert present == (SO_MOKDAN, SUK_JEOKHAN, BEAST_HUSBAND)


def test_adherence_passes_when_renderings_present():
    translation = "So Mok-dan looked at Suk Jeok-han. He was her beast-husband."
    report = check_adherence(SOURCE, translation, (SO_MOKDAN, SUK_JEOKHAN, ABSENT, BEAST_HUSBAND))
    assert report.present == 3
    assert report.violations == ()


def test_adherence_flags_missing_rendering():
    translation = "So Mokdan looked at Suk Jeok-han. He was her beast-husband."
    report = check_adherence(SOURCE, translation, (SO_MOKDAN, SUK_JEOKHAN, BEAST_HUSBAND))
    assert report.violations == (SO_MOKDAN,)


def test_adherence_is_case_insensitive_and_accepts_inflection():
    translation = "SO MOK-DAN's beast-husbands bowed before suk jeok-han."
    report = check_adherence(SOURCE, translation, (SO_MOKDAN, SUK_JEOKHAN, BEAST_HUSBAND))
    assert report.violations == ()


def test_absent_terms_never_counted_or_flagged():
    report = check_adherence(SOURCE, "irrelevant", (ABSENT,))
    assert report.present == 0
    assert report.violations == ()
