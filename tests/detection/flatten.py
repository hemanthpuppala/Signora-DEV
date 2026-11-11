"""A fillable PDF's flat twin: every form field removed, the printed page kept (findings F9).

The twin's places are known from the original's fields, so it tests reading a flat document whose
lines are drawn, typed or printed in a form's cells.

    apps/api/.venv/bin/python tests/detection/flatten.py <fillable.pdf> [<out.pdf>]

Without ``out``, the twin is written beside the original as ``<name>-flat.pdf``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf


def flatten(source: Path, out: Path) -> int:
    """Write the twin; the number of form fields removed."""
    removed = 0
    with pymupdf.open(source) as document:
        for page in document:
            for widget in list(page.widgets() or []):
                page.delete_widget(widget)
                removed += 1
        document.save(out, garbage=3, deflate=True)
    return removed


def main() -> None:
    source = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else source.with_name(f"{source.stem}-flat.pdf")
    print(f"{out}: {flatten(source, out)} form fields removed")  # noqa: T201 - a command-line tool


if __name__ == "__main__":
    main()
