"""Approving a version in review (Phase 6 LLD §1.3, §1.5, §2.1, §10.4, NFR-R2)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.db import Database
from tests.modules.documents.conftest import csrf_headers, log_in
from tests.modules.identity_access.conftest import Account
from tests.modules.review.test_revisions import _revise, _version
from tests.modules.review.test_save import (
    DOCUMENTS,
    _body,
    _drawn,
    _in_review,
    _save,
    _view,
    large_set,
    with_statistics,
)


def _approve(api: TestClient, document_id: str, version_id: str, **override: Any) -> Any:
    view = _view(api, document_id, version_id)
    body = {"revision": view["revision"], "accepted": [w["code"] for w in view["warnings"]]}
    return api.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/approve",
        json={**body, **override},
        headers=csrf_headers(api),
    )


def _metrics(db: Database, version_id: str) -> Any:
    with db.unit_of_work() as uow:
        return uow.session.execute(
            text("SELECT * FROM review_metrics WHERE version_id = :v"), {"v": version_id}
        ).one()


def test_approving_freezes_records_the_warnings_and_measures_an_untouched_proposal(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    view = _view(owner, document_id, version_id)
    places = sum(len(f["placements"]) for f in view["fields"])
    flagged = sum(1 for f in view["fields"] if f["needs_review"])

    approved = _approve(owner, document_id, version_id)

    assert approved.status_code == 204, approved.text
    version = _version(owner, document_id, 1)
    assert (version["status"], version["is_current"]) == ("approved", True)
    assert version["approved"]["by"]["id"]
    after = _view(owner, document_id, version_id)
    assert (after["status"], after["warnings"]) == ("approved", [])
    metrics = _metrics(committing_db, version_id)
    assert (metrics.true_positives, metrics.false_positives, metrics.false_negatives) == (
        places,
        0,
        0,
    )
    assert (metrics.precision, metrics.recall, metrics.f1, metrics.mean_iou) == (1, 1, 1, 1)
    assert (metrics.relabelled, metrics.retyped, metrics.reassigned) == (0, 0, 0)
    assert metrics.flags_accepted == flagged
    assert str(metrics.baseline_version_id) == version_id
    with committing_db.unit_of_work() as uow:
        accepted = uow.session.execute(
            text("SELECT accepted FROM version_reviews WHERE version_id = :v"), {"v": version_id}
        ).scalar_one()
        audit = uow.session.execute(
            text(
                "SELECT data FROM audit_events WHERE action = 'document.version_approved' "
                "AND subject_id = :d"
            ),
            {"d": document_id},
        ).scalar_one()
    assert [w["code"] for w in accepted] == [w["code"] for w in view["warnings"]]
    assert audit["accepted"] == [w["code"] for w in view["warnings"]]
    assert audit["metrics"]["true_positives"] == places

    again = _approve(owner, document_id, version_id, revision=view["revision"])
    assert (again.status_code, again.json()["code"]) == (409, "version-not-in-review")
    found_again = owner.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/detection", headers=csrf_headers(owner)
    )
    assert (found_again.status_code, found_again.json()["code"]) == (409, "fields-approved")


def test_metrics_measure_what_the_reviewer_changed(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    view = _view(owner, document_id, version_id)
    body = _body(view)
    places = sum(len(f["places"]) for f in body["fields"])
    body["fields"][0]["label"] = "Something else entirely"
    removed = body["fields"].pop()
    body["fields"].append(_drawn("Matter number", None, x=300, y=40))
    assert _save(owner, document_id, version_id, body).status_code == 200

    assert _approve(owner, document_id, version_id).status_code == 204

    metrics = _metrics(committing_db, version_id)
    gone = len(removed["places"])
    assert (metrics.true_positives, metrics.false_positives, metrics.false_negatives) == (
        places - gone,
        gone,
        1,
    )
    assert metrics.relabelled == 1


def test_an_edited_versions_metrics_compare_with_its_sources_proposal(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    document_id, source_id = _in_review(owner, run, detect)
    assert _approve(owner, document_id, source_id).status_code == 204
    body = _body(_view(owner, document_id, source_id))
    body["parties"][0]["label"] = "The Customer"  # a rename is not a reassignment
    made = _revise(owner, document_id, source_id, body).json()

    assert _approve(owner, document_id, made["version_id"]).status_code == 204

    metrics = _metrics(committing_db, made["version_id"])
    assert str(metrics.baseline_version_id) == source_id
    assert (metrics.false_positives, metrics.false_negatives, metrics.reassigned) == (0, 0, 0)
    assert _version(owner, document_id, 2)["is_current"]


def test_a_stale_approval_or_unseen_warnings_are_refused(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
) -> None:
    document_id, version_id = _in_review(owner, run, detect)
    view = _view(owner, document_id, version_id)
    body = _body(view)
    party = body["parties"][0]["id"]
    body["fields"].append(_drawn("Tax number", party, holds="tax_id", x=300, y=40))
    assert _save(owner, document_id, version_id, body).status_code == 200
    codes = [w["code"] for w in _view(owner, document_id, version_id)["warnings"]]
    assert "private_value" in codes

    stale = _approve(owner, document_id, version_id, revision=view["revision"])
    assert (stale.status_code, stale.json()["code"]) == (409, "fields-changed")
    unseen = _approve(owner, document_id, version_id, accepted=[])
    assert (unseen.status_code, unseen.json()["code"]) == (409, "warnings-changed")
    unknown = _approve(owner, document_id, version_id, accepted=["not_a_warning"])
    assert unknown.status_code == 422
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert _approve(theirs, document_id, version_id).status_code == 403
    assert _version(owner, document_id, 1)["status"] == "ready"


def test_more_warnings_than_kinds_of_warning_are_accepted(
    owner: TestClient, run: Callable[..., None], detect: Callable[..., None]
) -> None:
    """§2.1: the page lists every warning (ten private values are ten); what is accepted is the
    set of their kinds, however many of each, so such a version can still be approved."""
    document_id, version_id = _in_review(owner, run, detect)
    body = _body(_view(owner, document_id, version_id))
    party = body["parties"][0]["id"]
    for n in range(10):
        body["fields"].append(
            _drawn(f"Tax number {n}", party, holds="tax_id", x=300, y=600 + 16 * n)
        )
    assert _save(owner, document_id, version_id, body).status_code == 200
    warnings = _view(owner, document_id, version_id)["warnings"]
    assert sum(1 for w in warnings if w["code"] == "private_value") == 10

    assert _approve(owner, document_id, version_id).status_code == 204  # one code per warning
    assert _version(owner, document_id, 1)["status"] == "approved"


def test_two_thousand_fields_approve_in_under_a_second(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    """NFR-R2: 2 000 fields and 4 000 places, metrics included."""
    document_id, version_id = _in_review(owner, run, detect)
    body = large_set(_body(_view(owner, document_id, version_id)))
    assert _save(owner, document_id, version_id, body).status_code == 200
    view = _view(owner, document_id, version_id)
    with_statistics(committing_db)

    started = time.monotonic()
    approved = owner.post(
        f"{DOCUMENTS}/{document_id}/versions/{version_id}/approve",
        json={"revision": view["revision"], "accepted": [w["code"] for w in view["warnings"]]},
        headers=csrf_headers(owner),
    )
    elapsed = time.monotonic() - started

    assert approved.status_code == 204, approved.text
    assert elapsed < 1.0, f"approve took {elapsed:.2f} s"


def test_an_approval_takes_the_documents_lock_before_any_other(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    committing_db: Database,
) -> None:
    """One order of locks for every change of a document: its row, then a version's, then the
    audit chain's. An approval took the version's and the audit chain's first and the document's
    last (to move the current version), so it could deadlock with a rename, an upload or a new
    search for fields, which hold the document's and then write their audit entry."""
    document_id, version_id = _in_review(owner, run, detect)
    answer: list[Any] = []
    approving = threading.Thread(
        target=lambda: answer.append(_approve(owner, document_id, version_id))
    )

    with committing_db.unit_of_work() as other:  # another change of the document, mid-way
        other.session.execute(
            text("SELECT id FROM documents WHERE id = :d FOR NO KEY UPDATE"), {"d": document_id}
        )
        approving.start()
        with committing_db.unit_of_work() as watch:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:  # until the approval waits for a lock
                waiting = watch.session.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND wait_event_type = 'Lock'"
                    )
                ).scalar_one()
                if waiting:
                    break
                time.sleep(0.05)
            assert waiting == 1
            # It waits for the document holding nothing another change of the document needs: the
            # audit chain's lock is not taken yet.
            advisory = watch.session.execute(
                text(
                    "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                    "WHERE a.wait_event_type = 'Lock' AND l.granted AND l.locktype = 'advisory'"
                )
            ).scalar_one()
            assert advisory == 0

    approving.join(timeout=20)
    assert answer and answer[0].status_code == 204
