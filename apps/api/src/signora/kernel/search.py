"""Search across a list's texts (ADR S-1): one rule for every module that lists things.

A text matches when it contains the query, or when the query is close to some run of words in it
(PostgreSQL pg_trgm's word similarity, at least ``THRESHOLD``): "northwnd" finds "Northwind". The
score is 1 for containing it, else the word similarity; best match first, the list's own date
breaking ties. Modules name their columns (constants of their own) and keep their own queries;
each searched column has a trigram GIN index, so a match is an index lookup.

One or two characters have no trigrams to compare, so they match by containing only.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signora.kernel.errors import FieldError, ValidationFailed

QUERY_MAX = 100
# Typos score about 0.6 and above against the word they mean; unrelated short words below 0.3.
THRESHOLD = 0.5


@dataclass(frozen=True)
class Search:
    words: str  # normalised: trimmed, single spaces, at most QUERY_MAX characters

    @property
    def params(self) -> dict[str, str]:
        """The bound parameters the SQL of ``matches`` and ``score`` reads."""
        escaped = self.words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return {"search_q": self.words, "search_like": f"%{escaped}%"}


def normalize(raw: str | None) -> Search | None:
    """The query to search for, or ``None`` for no search (absent, or only spaces)."""
    if raw is None:
        return None
    words = " ".join(raw.split())[:QUERY_MAX]
    return Search(words) if words else None


def matches(columns: Sequence[str]) -> str:
    """SQL true when any of ``columns`` matches: contains the query, or is close to it."""
    return "(" + " OR ".join(f"({c} ILIKE :search_like OR :search_q <% {c})" for c in columns) + ")"


def score(columns: Sequence[str]) -> str:
    """SQL for the best score among ``columns``: 1 for containing the query, else similarity; a
    double precision, so a cursor carries it exactly."""
    parts = [
        f"CASE WHEN {c} ILIKE :search_like THEN CAST(1 AS double precision) "
        f"ELSE CAST(word_similarity(:search_q, {c}) AS double precision) END"
        for c in columns
    ]
    return f"GREATEST({', '.join(parts)})" if len(parts) > 1 else parts[0]


def begin(session: Session) -> None:
    """Set the similarity threshold for this transaction (``<%`` reads it, and its index too)."""
    session.execute(text(f"SET LOCAL pg_trgm.word_similarity_threshold = {THRESHOLD}"))


# --- the cursor of a page of matches: (score, date, id) -------------------------------------------


@dataclass(frozen=True)
class After:
    score: float
    at: datetime
    id: uuid.UUID


def cursor(score_value: float, at: datetime, item_id: uuid.UUID) -> str:
    raw = f"{score_value!r}|{at.isoformat()}|{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def after(raw: str | None) -> After | None:
    if not raw:
        return None
    try:
        value, at, item_id = (
            base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode().split("|")
        )
        return After(float(value), datetime.fromisoformat(at), uuid.UUID(item_id))
    except (ValueError, UnicodeDecodeError):
        raise ValidationFailed([FieldError("cursor", "Start the list again")]) from None


def after_params(position: After | None) -> dict[str, Any]:
    return {
        "after_score": position.score if position else None,
        "after_at": position.at if position else None,
        "after_id": position.id if position else None,
    }


def beyond(score_sql: str, at_sql: str, id_sql: str, *, soonest_first: bool = False) -> str:
    """SQL for the rows after the cursor, in the order best match first, then by date: newest
    first, or with ``soonest_first`` the earliest first (a deadline), then id the same way.
    ``score_sql``, ``at_sql`` and ``id_sql`` are the query's own expressions for them."""
    score = "CAST(:after_score AS double precision)"
    at = "CAST(:after_at AS timestamptz)"
    after_id = "CAST(:after_id AS uuid)"
    then = ">" if soonest_first else "<"
    return (
        f"({score} IS NULL OR {score_sql} < {score} OR "
        f"({score_sql} = {score} AND ({at_sql}, {id_sql}) {then} ({at}, {after_id})))"
    )


def order(score_sql: str, at_sql: str, id_sql: str, *, soonest_first: bool = False) -> str:
    """The ORDER BY that ``beyond`` pages through."""
    way = "ASC" if soonest_first else "DESC"
    return f"{score_sql} DESC, {at_sql} {way}, {id_sql} {way}"
