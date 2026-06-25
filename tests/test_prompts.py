import pytest

from harness.models import ChapterSummary, GlossaryEntry, TranslationContext
from harness.prompts import (
    build_system_blocks,
    build_user_message,
    load_system_prompt,
    render_glossary_table,
)

GLOSSARY = (
    GlossaryEntry("김철수", "Kim Cheol-su", "person", "protagonist"),
    GlossaryEntry("청룡문", "Azure Dragon Sect", "organization"),
    GlossaryEntry("뇌전보", "Lightning Steps", "technique", "movement skill"),
)


def test_glossary_table_preserves_append_order_and_renders_verbatim():
    table = render_glossary_table(GLOSSARY)
    lines = table.splitlines()
    assert lines[0] == "김철수 | Kim Cheol-su | person | protagonist"
    assert lines[1] == "청룡문 | Azure Dragon Sect | organization"
    assert lines[2] == "뇌전보 | Lightning Steps | technique | movement skill"


def test_system_prompt_substitutes_honorifics_policy():
    keep = load_system_prompt("keep")
    localize = load_system_prompt("localize")
    assert "{HONORIFICS_POLICY}" not in keep
    assert "-nim" in keep
    assert "Never romanize Korean honorifics" in localize


def test_invalid_honorifics_variant_rejected():
    with pytest.raises(ValueError, match="honorifics"):
        load_system_prompt("emoji")


def test_system_blocks_carry_cache_control():
    blocks = build_system_blocks(TranslationContext(glossary=GLOSSARY))
    assert len(blocks) == 2
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)
    assert "Azure Dragon Sect" in blocks[1]["text"]


def test_chapter_one_conditions_omit_empty_sections():
    # Empty glossary, no summaries: one system block, no context tags.
    blocks = build_system_blocks(TranslationContext())
    assert len(blocks) == 1
    message = build_user_message(TranslationContext(), "첫 번째 장의 본문.")
    assert "<story_so_far>" not in message
    assert "<previous_chapter_summaries>" not in message
    assert "<chapter>\n첫 번째 장의 본문.\n</chapter>" in message


def test_user_message_includes_context_sections_when_present():
    context = TranslationContext(
        arc_summary="Cheol-su joined the Azure Dragon Sect.",
        chapter_summaries=(ChapterSummary(11, "He won the entrance duel."),),
    )
    message = build_user_message(context, "본문")
    assert "<story_so_far>" in message
    assert "Ch.11: He won the entrance duel." in message
    assert message.index("<story_so_far>") < message.index("<chapter>")


def test_empty_chapter_rejected():
    with pytest.raises(ValueError, match="chapter_text"):
        build_user_message(TranslationContext(), "   ")
