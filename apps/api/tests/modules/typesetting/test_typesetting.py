"""Fonts and the rule that fits a value to its box (Phase 7b LLD)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from signora.modules.typesetting import DEFAULT_FONT, FONTS
from signora.modules.typesetting.fit import (
    MIN_SIZE,
    baseline,
    fitted_size,
    left_edge,
    place_size,
)
from signora.modules.typesetting.fonts import font_path, metrics


def test_every_font_ships_with_its_licence_and_the_default_is_listed() -> None:
    assert len({f.id for f in FONTS}) == len(FONTS)
    assert DEFAULT_FONT in {f.id for f in FONTS}
    for f in FONTS:
        path = font_path(f.id)
        assert path.is_file()
        assert (path.parent / f.licence).read_text().strip()
        assert metrics(f.id).text_length("Agreement", fontsize=1) > 0


def test_a_value_takes_the_agreements_text_size_or_a_share_of_its_box() -> None:
    assert place_size(10.0, (0, 0, 100, 40)) == 10.0
    assert place_size(None, (0, 0, 100, 10)) == pytest.approx(7.2)
    assert place_size(None, (0, 0, 100, 40)) == 11.0  # no larger than body text


def test_a_value_fits_shrinks_or_is_refused() -> None:
    box = (0, 0, 40, 14)  # the "20__" of a year: a short box
    assert fitted_size("26", box, 11.0, DEFAULT_FONT) == 11.0
    shrunk = fitted_size("2026-11-09", box, 11.0, DEFAULT_FONT)
    assert shrunk is not None and MIN_SIZE <= shrunk < 11.0
    assert fitted_size("Northwind Holdings International", box, 11.0, DEFAULT_FONT) is None
    # A short box starts below the smallest size; only its width can refuse a value.
    assert fitted_size("Value 7", (0, 0, 160, 8), 5.76, DEFAULT_FONT) == 5.76


def test_a_value_sits_on_its_line() -> None:
    assert baseline((0, 100, 50, 120), 10.0) == pytest.approx(118.2)
    assert baseline((0, 100, 50, 120), 6.0) == pytest.approx(118.5)  # never closer than 1.5 pt


def test_a_font_is_served_to_anyone_and_cached_for_good(client: TestClient) -> None:
    served = client.get(f"/api/v1/fonts/{DEFAULT_FONT}")

    assert served.status_code == 200
    assert served.headers["content-type"] == "font/ttf"
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert served.content == font_path(DEFAULT_FONT).read_bytes()
    assert client.get("/api/v1/fonts/comic-sans").status_code == 404


def test_a_value_sits_in_the_middle_of_its_box_and_never_leaves_it() -> None:
    box = (100.0, 0.0, 300.0, 14.0)
    width = metrics(DEFAULT_FONT).text_length("26", fontsize=12)
    assert left_edge(box, "26", 12, DEFAULT_FONT) == pytest.approx(100 + (200 - width) / 2)
    long = "x" * 200  # wider than the box: drawn from its left edge (it had to shrink)
    assert left_edge(box, long, 12, DEFAULT_FONT) == 100.0
