"""Tests for token-subset adherence matching (fix #3)."""

from harness.adherence import check_adherence
from harness.models import GlossaryEntry

SRC = "검성 척준성이 페더백을 만났다. 마창에서."


def test_word_order_variant_passes():
    # Glossary says "Cheok Jun-seong the Sword Saint"; translation reorders it.
    g = (GlossaryEntry("검성 척준성", "Cheok Jun-seong the Sword Saint", "person", ""),)
    tr = "Sword Saint Cheok Jun-seong stepped forward."
    assert check_adherence(SRC, tr, g).violations == ()


def test_stopwords_and_possessive_ignored():
    g = (GlossaryEntry("마창", "Hall of the Sword", "place", ""),)
    tr = "He entered the Sword Hall's gate."  # all content tokens present, reordered
    assert check_adherence(SRC, tr, g).violations == ()


def test_genuine_divergence_still_flagged():
    # "Featherback" simply does not appear -> real miss, must still flag.
    g = (GlossaryEntry("페더백", "Featherback", "person", ""),)
    tr = "Morg Myu Pedebaek nodded."
    assert len(check_adherence(SRC, tr, g).violations) == 1


def test_plain_substring_still_passes():
    g = (GlossaryEntry("페더백", "Featherback", "person", ""),)
    tr = "Featherback's ledger lay open."
    assert check_adherence(SRC, tr, g).violations == ()


def test_partial_token_match_is_a_miss():
    # Only one of two content tokens present -> not adherent.
    g = (GlossaryEntry("마창", "Magic Warehouse", "place", ""),)
    tr = "The warehouse was empty."  # has "warehouse", missing "magic"
    assert len(check_adherence(SRC, tr, g).violations) == 1
