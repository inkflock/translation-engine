"""Tests for U3 prompt variant assembly."""

import pytest

from harness.models import GlossaryEntry, TranslationContext
from harness.prompts import (
    build_system_blocks_for,
    load_experiment_prompt,
    load_system_prompt,
    load_system_prompt_with_output,
)


def test_output_swap_keeps_shared_prefix_identical():
    base = load_system_prompt("keep")
    json_variant = load_system_prompt_with_output("keep", "output_json.md")
    cut = base.find("# Output format")
    assert json_variant[:cut] == base[:cut]


def test_json_variant_has_json_instructions_and_no_xml_tags():
    variant = load_system_prompt_with_output("keep", "output_json.md")
    assert '"translation"' in variant
    assert "<translation>" not in variant


def test_translation_only_variant_has_single_section():
    variant = load_system_prompt_with_output("keep", "output_translation_only.md")
    assert "<translation>" in variant
    assert "<new_glossary_terms>" not in variant


def test_unknown_spec_file_raises():
    with pytest.raises(FileNotFoundError):
        load_system_prompt_with_output("keep", "does_not_exist.md")


def test_extract_prompt_loads():
    text = load_experiment_prompt("extract_system.md")
    assert "<new_glossary_terms>" in text
    assert "<chapter_summary>" in text


def test_custom_blocks_keep_cache_control_and_glossary_block():
    context = TranslationContext(glossary=(GlossaryEntry("소목단", "So Mok-dan", "person"),))
    blocks = build_system_blocks_for("custom instructions", context)
    assert blocks[0]["text"] == "custom instructions"
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in blocks)
    assert "소목단 | So Mok-dan" in blocks[1]["text"]
