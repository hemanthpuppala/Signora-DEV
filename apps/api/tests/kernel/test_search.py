"""The search rule (ADR S-1): what a query becomes and the SQL a list's columns make."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from signora.kernel import search
from signora.kernel.errors import ValidationFailed


def test_a_query_is_trimmed_to_single_spaces_and_a_limit_and_blank_is_no_search() -> None:
    assert search.normalize(None) is None
    assert search.normalize("   ") is None
    assert search.normalize("  Maya \t  Chen ") == search.Search("Maya Chen")
    long = search.normalize("x" * 500)
    assert long is not None and len(long.words) == search.QUERY_MAX


def test_its_own_percent_and_underscore_are_letters() -> None:
    query = search.normalize(r"100%_a\b")
    assert query is not None
    assert query.params == {"search_q": r"100%_a\b", "search_like": r"%100\%\_a\\b%"}


def test_the_sql_matches_and_scores_every_column_by_name_only() -> None:
    columns = ("e.title", "d.name")
    assert search.matches(columns).count("ILIKE :search_like") == 2
    assert "GREATEST(" in search.score(columns)
    assert "GREATEST(" not in search.score(("d.name",))
    assert ":search_q <% d.name" in search.matches(columns)


def test_a_cursor_carries_its_score_exactly_and_a_forged_one_is_refused() -> None:
    at = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
    item = uuid.uuid4()
    score = 0.6153846383094788  # a word similarity, as PostgreSQL gives it
    assert search.after(search.cursor(score, at, item)) == search.After(score, at, item)
    with pytest.raises(ValidationFailed):
        search.after("not-a-cursor")
