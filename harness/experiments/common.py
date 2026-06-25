"""Shared plumbing for U3 experiment runners: output saving and summaries."""

from __future__ import annotations

from pathlib import Path

RESULTS_DIR = Path("results")

DEFAULT_CHAPTERS = (
    "fixtures/beastworld-favorite/ch001.txt",
    "fixtures/villainess-shura-field/ch001.txt",
)


def save_output(experiment: str, variant: str, chapter_path: str, text: str, base: str = "u3") -> Path:
    """Save one model output for human side-by-side review; returns the path."""
    slug = Path(chapter_path).parent.name + "-" + Path(chapter_path).stem
    out = RESULTS_DIR / base / experiment / variant
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{slug}.md"
    path.write_text(text, encoding="utf-8")
    return path


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]
    line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for row in rows:
        print(" | ".join(str(c).ljust(w) for c, w in zip(row, widths)))
