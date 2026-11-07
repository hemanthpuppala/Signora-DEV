"""Wording helpers of account emails (Owner / Editor / Viewer copy)."""

from __future__ import annotations

from datetime import UTC, datetime

from signora.modules.identity_access.emails import day_month, role_sentence, with_article


def test_articles_follow_the_role_name() -> None:
    assert with_article("Viewer") == "a Viewer"
    assert with_article("Editor") == "an Editor"
    assert with_article("Owner") == "an Owner"
    assert with_article("Reviewer") == "a Reviewer"  # a company's own role works too


def test_the_role_sentence_comes_from_the_roles_description() -> None:
    assert role_sentence("Editor", "Can create and send agreements.") == (
        "As an Editor, you can create and send agreements."
    )
    assert role_sentence("Custom", "") == ""


def test_dates_read_like_people_write_them() -> None:
    assert day_month(datetime(2026, 11, 14, tzinfo=UTC)) == "14 November"
    assert day_month(datetime(2026, 3, 2, tzinfo=UTC)) == "2 March"
