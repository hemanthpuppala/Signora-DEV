"""Pure department rules (Phase 3 LLD topic 1). No web framework or database imports."""

from __future__ import annotations

NAME_MAX = 80
DESCRIPTION_MAX = 500


def normalize_name(raw: str) -> str:
    """Trim and collapse runs of whitespace; keep the casing as typed."""
    return " ".join(raw.split())


def name_problem(name: str) -> str | None:
    if not name:
        return "Enter a name"
    if len(name) > NAME_MAX:
        return f"Use {NAME_MAX} or fewer characters"
    return None


def description_problem(description: str) -> str | None:
    if len(description) > DESCRIPTION_MAX:
        return f"Use {DESCRIPTION_MAX} or fewer characters"
    return None
