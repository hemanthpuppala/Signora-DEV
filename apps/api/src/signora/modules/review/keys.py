"""Field keys (Phase 5 LLD §4.3, Phase 6 §11): ``<party>.<value>`` or ``<owner>.<label words>``.

One home for naming, used when detection proposes fields and when a person saves them.
"""

from __future__ import annotations

import re

KEY_WORDS_MAX = 40


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def name_words(label: str, role: str | None) -> str:
    """The label as key words: "Recipient bank name" under recipient is ``bank_name``; cut at a word
    boundary when long."""
    words = slug(label)
    if role:
        words = re.sub(rf"^{re.escape(role)}_?(?:s_)?", "", words)
    if len(words) > KEY_WORDS_MAX:
        words = words[:KEY_WORDS_MAX].rsplit("_", 1)[0]
    return words or "field"


def unique(base: str, taken: set[str]) -> str:
    """``base``, or ``base_2``, ``base_3``… whichever is free; it is then taken."""
    key, n = base, 2
    while key in taken:
        key, n = f"{base}_{n}", n + 1
    taken.add(key)
    return key
