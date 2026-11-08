"""Pure department rules (Phase 3 LLD topic 1). No web framework or database imports."""

from __future__ import annotations

NAME_MAX = 80
DESCRIPTION_MAX = 500
# Settings ranges (Phase 3 LLD topic 3); the database checks the same bounds.
REMINDER_INTERVAL_HOURS = (1, 720)
MAX_REMINDERS = (0, 20)
EXPIRY_DAYS = (1, 365)
NOTIFY_EMAILS_MAX = 5


def normalize_name(raw: str) -> str:
    """Trim and collapse runs of whitespace; keep the casing as typed."""
    return " ".join(raw.split())


def name_problem(name: str) -> str | None:
    if not name:
        return "Enter a name"
    if len(name) > NAME_MAX:
        return f"Use {NAME_MAX} or fewer characters"
    return None


def range_problem(value: int, bounds: tuple[int, int]) -> str | None:
    low, high = bounds
    if not low <= value <= high:
        return f"Choose a value from {low} to {high}"
    return None


def description_problem(description: str) -> str | None:
    if len(description) > DESCRIPTION_MAX:
        return f"Use {DESCRIPTION_MAX} or fewer characters"
    return None
