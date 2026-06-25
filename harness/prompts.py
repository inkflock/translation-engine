"""Prompt assembly — implements the order documented in prompts/assembly.md."""

from __future__ import annotations

from pathlib import Path

from harness.models import GlossaryEntry, TranslationContext

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

HONORIFICS_VARIANTS = ("keep", "localize")

OUTPUT_FORMAT_HEADING = "# Output format"


def load_system_prompt(honorifics: str = "keep") -> str:
    if honorifics not in HONORIFICS_VARIANTS:
        raise ValueError(f"honorifics must be one of {HONORIFICS_VARIANTS}, got {honorifics!r}")
    template = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")
    policy = (PROMPTS_DIR / f"honorifics_{honorifics}.md").read_text(encoding="utf-8").strip()
    return template.replace("{HONORIFICS_POLICY}", policy)


def load_system_prompt_with_output(honorifics: str, output_spec_file: str) -> str:
    """System prompt with its `# Output format` section replaced (U3 variants).

    Everything before the output-format heading is identical to the canonical
    prompt, so format experiments only vary the thing being measured.
    """
    base = load_system_prompt(honorifics)
    idx = base.find(OUTPUT_FORMAT_HEADING)
    if idx == -1:
        raise ValueError(f"system.md is missing the {OUTPUT_FORMAT_HEADING!r} section")
    spec = (PROMPTS_DIR / "experiments" / output_spec_file).read_text(encoding="utf-8").strip()
    return base[:idx] + spec + "\n"


def load_experiment_prompt(name: str) -> str:
    """A standalone experiment prompt from prompts/experiments/ (e.g. extraction)."""
    return (PROMPTS_DIR / "experiments" / name).read_text(encoding="utf-8")


def render_glossary_table(entries: tuple[GlossaryEntry, ...]) -> str:
    """Render entries in the given order — callers keep glossaries append-only
    so the cached prompt prefix stays stable across chapters."""
    lines = [f"{e.korean} | {e.english} | {e.category} | {e.note}".rstrip(" |") for e in entries]
    return "\n".join(lines)


def build_system_blocks(context: TranslationContext, honorifics: str = "keep") -> list[dict]:
    """System blocks with cache_control breakpoints (instructions, then glossary)."""
    return build_system_blocks_for(load_system_prompt(honorifics), context)


def build_system_blocks_for(system_text: str, context: TranslationContext) -> list[dict]:
    """Same block/cache structure as build_system_blocks, custom instructions text."""
    blocks: list[dict] = [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if context.glossary:
        blocks.append(
            {
                "type": "text",
                "text": "# Glossary of established terms\n\n"
                + render_glossary_table(context.glossary),
                "cache_control": {"type": "ephemeral"},
            }
        )
    return blocks


def build_user_message(context: TranslationContext, chapter_text: str) -> str:
    if not chapter_text.strip():
        raise ValueError("chapter_text must be non-empty")
    parts: list[str] = []
    if context.arc_summary.strip():
        parts.append(f"<story_so_far>\n{context.arc_summary.strip()}\n</story_so_far>")
    if context.chapter_summaries:
        lines = [f"Ch.{s.chapter}: {s.summary}" for s in context.chapter_summaries]
        parts.append(
            "<previous_chapter_summaries>\n"
            + "\n".join(lines)
            + "\n</previous_chapter_summaries>"
        )
    parts.append(f"<chapter>\n{chapter_text.strip()}\n</chapter>")
    return "\n\n".join(parts)
