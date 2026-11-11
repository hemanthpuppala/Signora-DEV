"""The review metrics' matching and measures (Phase 6 LLD §1.5, §11; platform §7.6)."""

from __future__ import annotations

import uuid

import pytest

from signora.modules.review.metrics import ApprovedPlace, BaselinePlace, iou, match, measure

CLIENT, VENDOR = uuid.uuid4(), uuid.uuid4()


def proposed(
    rect: tuple[float, float, float, float],
    holds: str = "text",
    page: int = 1,
    label: str = "Name",
    party: uuid.UUID | None = CLIENT,
) -> BaselinePlace:
    return BaselinePlace(page, rect, holds, label, "role" if party else "sender", party)


def approved(
    rect: tuple[float, float, float, float],
    holds: str = "text",
    page: int = 1,
    label: str = "Name",
    party: uuid.UUID | None = CLIENT,
    field: uuid.UUID | None = None,
) -> ApprovedPlace:
    return ApprovedPlace(
        field or uuid.uuid4(), page, rect, holds, label, "role" if party else "sender", party
    )


def test_iou() -> None:
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)
    assert iou((0, 0, 10, 10), (10, 0, 20, 10)) == 0.0  # touching is not overlapping


def test_matching_is_one_to_one_greedy_by_iou_within_a_page_and_family() -> None:
    ours = [proposed((0, 0, 100, 20)), proposed((0, 100, 100, 120), holds="signature")]
    theirs = [
        approved((10, 0, 100, 20)),  # IoU 0.9 with ours[0]
        approved((0, 0, 100, 20)),  # IoU 1.0 with ours[0]: wins it
        approved((0, 100, 100, 120), holds="text"),  # same box, another family
        approved((0, 0, 100, 20), page=2),  # another page
        approved((0, 0, 100, 20), holds="email"),  # data family too, but ours[0] is taken
    ]

    assert match(ours, theirs) == [(0, 1, 1.0)]


def test_a_box_moved_more_than_half_away_is_not_a_match() -> None:
    assert match([proposed((0, 0, 100, 20))], [approved((40, 0, 140, 20))]) == []  # IoU 0.43
    ((i, j, score),) = match([proposed((0, 0, 100, 20))], [approved((30, 0, 130, 20))])
    assert (i, j) == (0, 0)
    assert score == pytest.approx(70 / 130)


def test_measures_count_places_and_compare_matched_fields() -> None:
    field = uuid.uuid4()
    ours = [
        proposed((0, 0, 100, 20), label="Name"),
        proposed((0, 50, 100, 70), label="Email", holds="email"),
        proposed((0, 100, 100, 120), label="Company"),
        proposed((0, 200, 100, 220), label="Removed"),
    ]
    theirs = [
        approved((0, 0, 100, 20), label=" name ", field=field),  # unchanged (case, spaces)
        approved((0, 50, 100, 70), label="Work email", holds="text"),  # relabelled, retyped
        approved((0, 100, 100, 120), label="Company", party=VENDOR),  # reassigned
        approved((0, 300, 100, 320), label="Added"),  # drawn by hand
    ]

    metrics = measure(ours, theirs)

    assert (metrics.true_positives, metrics.false_positives, metrics.false_negatives) == (3, 1, 1)
    assert (metrics.precision, metrics.recall, metrics.f1) == (0.75, 0.75, 0.75)
    assert (metrics.relabelled, metrics.retyped, metrics.reassigned) == (1, 1, 1)
    assert metrics.mean_iou == 1.0


def test_a_field_with_several_places_is_compared_once() -> None:
    field = uuid.uuid4()
    ours = [proposed((0, 0, 50, 20), label="Initials"), proposed((0, 0, 50, 20), page=2)]
    theirs = [
        approved((0, 0, 50, 20), label="Your initials", field=field),
        approved((0, 0, 50, 20), page=2, label="Your initials", field=field),
    ]

    assert measure(ours, theirs).relabelled == 1


def test_nothing_proposed_or_nothing_approved_leaves_ratios_undefined() -> None:
    nothing_proposed = measure([], [approved((0, 0, 10, 10))])
    assert (nothing_proposed.precision, nothing_proposed.recall) == (None, 0.0)
    assert (nothing_proposed.f1, nothing_proposed.mean_iou) == (None, None)
    empty = measure([], [])
    assert (empty.precision, empty.recall, empty.f1) == (None, None, None)


def test_a_baseline_place_moves_to_a_new_versions_party_ids() -> None:
    new_client = uuid.uuid4()
    place = proposed((0, 0, 10, 10))

    assert place.moved({CLIENT: new_client}).party_id == new_client
    assert place.moved({}).party_id is None  # the party was gone: a reassignment
    assert BaselinePlace.from_json(place.as_json()) == place
