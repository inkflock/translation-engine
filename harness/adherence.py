"""Glossary adherence checking for the U3 load experiment.

Given the Korean source, the English translation, and a glossary, report
which glossary terms appear in the source but whose established English
rendering is missing from the translation.

Matching is two-stage: a case-insensitive substring pass (catches verbatim
renderings and inflections), then a token-subset pass — every content word
of the rendering must appear as a word in the translation. The token pass
tolerates word-order differences ("Cheok Jun-seong the Sword Saint" vs
"Sword Saint Cheok Jun-seong") while still flagging genuine divergence
(a re-romanized or re-translated name whose words are simply absent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from harness.models import GlossaryEntry

_STOPWORDS = frozenset({"the", "of", "a", "an", "and", "s"})

# Korean grammatical material that legitimately attaches to a noun: particles
# (josa) and copula/predicate endings. A key followed by one of these is a real
# occurrence; a key followed by other Hangul (e.g. the noun-forming suffix 화 in
# 민주화) is a substring of a longer word and must NOT match.
_PARTICLES = (
    # particles (josa)
    "으로써", "으로서", "에서는", "에게서", "이라고", "이라는", "으로", "에서",
    "에게", "한테", "처럼", "만큼", "까지", "부터", "보다", "라고", "라는",
    "마저", "조차", "밖에", "이나", "은", "는", "이", "가", "을", "를", "과",
    "와", "의", "에", "로", "도", "만", "님", "씨", "들",
    # copula / predicate endings (noun + 이다 conjugations)
    "이었", "였다", "였고", "였어", "였", "이다", "이라", "이고", "이며",
    "이야", "이지", "예요", "입니", "인",
)


def _is_hangul(c: str) -> bool:
    return "가" <= c <= "힣"


def _korean_occurs(key: str, source: str) -> bool:
    """True if `key` appears in `source` as a standalone term, not as part of a
    longer Hangul word. A trailing Korean particle is allowed."""
    start = source.find(key)
    while start != -1:
        end = start + len(key)
        before_ok = start == 0 or not _is_hangul(source[start - 1])
        # trailing Hangul run after the key
        j = end
        while j < len(source) and _is_hangul(source[j]):
            j += 1
        run = source[end:j]
        after_ok = run == "" or any(run.startswith(p) for p in _PARTICLES)
        if before_ok and after_ok:
            return True
        start = source.find(key, start + 1)
    return False


def _words(text: str) -> set[str]:
    """Lowercased word tokens; non-alphanumeric (except hyphen) splits words."""
    return set(re.split(r"[^0-9a-z\-]+", text.lower())) - {""}


def _content_tokens(rendering: str) -> list[str]:
    return [w for w in _words(rendering) if w not in _STOPWORDS]


def _is_adherent(rendering: str, translation_lower: str, translation_words: set[str]) -> bool:
    if rendering.lower() in translation_lower:
        return True
    tokens = _content_tokens(rendering)
    return bool(tokens) and all(t in translation_words for t in tokens)


@dataclass(frozen=True)
class AdherenceReport:
    present: int
    violations: tuple[GlossaryEntry, ...]


def terms_in_source(
    source: str, glossary: tuple[GlossaryEntry, ...]
) -> tuple[GlossaryEntry, ...]:
    """Glossary entries whose Korean term occurs in the source chapter."""
    return tuple(e for e in glossary if _korean_occurs(e.korean, source))


def check_adherence(
    source: str, translation: str, glossary: tuple[GlossaryEntry, ...]
) -> AdherenceReport:
    present = terms_in_source(source, glossary)
    haystack = translation.lower()
    words = _words(translation)
    violations = tuple(
        e for e in present if not _is_adherent(e.english, haystack, words)
    )
    return AdherenceReport(present=len(present), violations=violations)
