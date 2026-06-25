"""Tests for boundary-aware Korean key matching in adherence (#4)."""

from harness.adherence import terms_in_source, check_adherence
from harness.models import GlossaryEntry

MINJU = GlossaryEntry("민주", "Minju", "person")
NAME = GlossaryEntry("강태광", "Gang Tae-gwang", "person")


def test_short_key_not_matched_inside_longer_word():
    # 민주 must NOT match inside 민주화 (democratization).
    assert terms_in_source("민주화 실패다 뭐다", (MINJU,)) == ()


def test_short_key_matched_with_trailing_particle():
    # 민주 + 를 (object particle) is a real occurrence of the name.
    assert terms_in_source("민주를 외쳤다", (MINJU,)) == (MINJU,)


def test_key_matched_standalone():
    assert terms_in_source("민주 said nothing", (MINJU,)) == (MINJU,)


def test_name_matched_with_subject_particle():
    assert terms_in_source("강태광이 말했다", (NAME,)) == (NAME,)


def test_key_not_matched_when_preceded_by_hangul():
    # part of a larger compound -> not a standalone occurrence
    assert terms_in_source("어떤민주주의", (MINJU,)) == ()


def test_adherence_no_false_positive_on_democratization():
    g = (MINJU,)
    # translation correctly says "democratization"; 민주 never occurs as the name
    report = check_adherence("민주화 실패", "the failure of democratization", g)
    assert report.present == 0
    assert report.violations == ()
