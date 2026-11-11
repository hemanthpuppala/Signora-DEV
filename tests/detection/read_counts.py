"""The read stage's pass mark on the local corpus (findings F9).

For every PDF in ``tests/fixtures/documents``: what the read stage finds (fields from, places
asked, places from drawn lines, places with a label). ``--check`` compares with the committed
``tests/expected/read-counts.json`` and fails on any difference; ``--write`` records the current
counts after a change has been looked at. Counts only: no document text is committed. The read
stage is deterministic, so a difference is a change in behaviour, never noise.

    apps/api/.venv/bin/python tests/detection/read_counts.py --check
    apps/api/.venv/bin/python tests/detection/read_counts.py --write
    ... --documents <folder>   another corpus folder (a worktree shares the main checkout's)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from signora.modules.detection.read import read_document

TESTS = Path(__file__).resolve().parents[1]
DOCUMENTS = TESTS / "fixtures" / "documents"
EXPECTED = TESTS / "expected" / "read-counts.json"


def counts(documents: Path) -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    for path in sorted(documents.glob("*.pdf")):
        reading = read_document(path.read_bytes())
        found[path.name] = {
            "fields_from": reading.fields_from,
            "asked": len(reading.asked),
            "drawn": sum(1 for field in reading.asked if field.drawn),
            "named": sum(1 for field in reading.asked if field.label),
        }
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--documents", type=Path, default=DOCUMENTS, help="the corpus folder")
    args = parser.parse_args()
    now = counts(args.documents)
    if args.write:
        EXPECTED.write_text(json.dumps(now, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{len(now)} documents recorded")  # noqa: T201 - a command-line tool
        return 0
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    problems = [
        f"{name}: expected {expected.get(name)}, read {now.get(name)}"
        for name in sorted(set(expected) | set(now))
        if name in expected and name in now and expected[name] != now[name]
    ]
    missing = sorted(set(expected) - set(now))
    for line in problems:
        print(line)  # noqa: T201
    if missing:
        print(f"not in the local corpus (skipped): {', '.join(missing)}")  # noqa: T201
    print(f"{len(now) - len(problems)} of {len(now)} documents as expected")  # noqa: T201
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
