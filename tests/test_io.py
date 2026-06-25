import json

import pytest

from harness.io import InputError, load_chapter, load_context, load_glossary


def test_missing_chapter_file_reports_clearly(tmp_path):
    with pytest.raises(InputError, match="not found"):
        load_chapter(tmp_path / "ch001.txt")


def test_empty_chapter_file_reports_clearly(tmp_path):
    p = tmp_path / "ch001.txt"
    p.write_text("   \n", encoding="utf-8")
    with pytest.raises(InputError, match="empty"):
        load_chapter(p)


def test_glossary_roundtrip(tmp_path):
    p = tmp_path / "glossary.json"
    p.write_text(
        json.dumps([{"korean": "김철수", "english": "Kim Cheol-su", "category": "person"}]),
        encoding="utf-8",
    )
    entries = load_glossary(p)
    assert entries[0].english == "Kim Cheol-su"
    assert entries[0].note == ""


def test_invalid_glossary_category_reports_file(tmp_path):
    p = tmp_path / "glossary.json"
    p.write_text(
        json.dumps([{"korean": "x", "english": "y", "category": "nonsense"}]), encoding="utf-8"
    )
    with pytest.raises(InputError, match="glossary"):
        load_glossary(p)


def test_context_loads_arc_and_summaries(tmp_path):
    p = tmp_path / "summaries.json"
    p.write_text(
        json.dumps(
            {
                "arc_summary": "The sect war begins.",
                "chapter_summaries": [{"chapter": 3, "summary": "A spy is revealed."}],
            }
        ),
        encoding="utf-8",
    )
    context = load_context(None, p)
    assert context.arc_summary == "The sect war begins."
    assert context.chapter_summaries[0].chapter == 3
    assert context.glossary == ()
