"""Completion (Phase 8 LLD §12): after the last countersignature one job makes the completed
document and its certificate, stores both with their fingerprints, completes the envelope and
emails everyone both PDFs; running it again changes nothing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from signora.kernel.blobstore import BlobRef, LocalBlobStore
from signora.kernel.config import Settings
from signora.kernel.db import Database
from signora.kernel.jobs import JobContext
from signora.modules.notifications.service import make_deliver
from signora.modules.notifications.transports import OutgoingEmail
from signora.modules.signing import completion
from tests.modules.identity_access.conftest import Account, idempotency_key
from tests.modules.signing.conftest import Sent, signable_envelope
from tests.modules.signing.test_consent import NO_CODE
from tests.modules.signing.test_countersign import _as, _signers_done
from tests.modules.signing.test_open import ENVELOPES, SIGN

COPIES = {**NO_CODE, "notify_emails": ["desk@firm.example"]}


@pytest.fixture
def browser(make_client: Callable[..., TestClient]) -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


def _countersign(owner: TestClient, sent: Sent) -> None:
    firm = str(sent.recipient("countersigner")["id"])
    _as(owner, "POST", f"{SIGN}/{firm}/consent", json={"disclosure_version": "esign-disclosure-v1"})
    _as(
        owner,
        "PUT",
        f"{SIGN}/{firm}/signature/signature",
        json={"method": "typed", "text": "Rosa Hale", "font": "allura"},
    )
    _as(owner, "POST", f"{SIGN}/{firm}/apply-all/signature")
    done = _as(owner, "POST", f"{SIGN}/{firm}/submit", headers=idempotency_key())
    assert done.status_code == 200, done.text


def _run_completion(db: Database, envelope_id: str, store: LocalBlobStore) -> None:
    with db.unit_of_work() as uow:
        job = uow.session.execute(
            text(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1 "
                "WHERE dedupe_key = :k RETURNING id, attempts"
            ),
            {"k": f"{completion.COMPLETE}:{envelope_id}"},
        ).one()
    payload = {"envelope_id": envelope_id}
    context = JobContext(job.id, completion.COMPLETE, payload, {}, job.attempts, db)
    completion.complete(context, store=store)


class Outbox:
    def __init__(self) -> None:
        self.name = "fake"
        self.sent: list[OutgoingEmail] = []

    def send(self, email: OutgoingEmail) -> str:
        self.sent.append(email)
        return email.message_id


def test_the_last_countersignature_completes_the_envelope_and_everyone_gets_both_pdfs(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
    committing_db: Database,
    settings: Settings,
) -> None:
    sent = signable_envelope(owner, run, detect, company, settings=COPIES)
    _signers_done(browser, sent)
    _countersign(owner, sent)

    store = LocalBlobStore(settings.blob_store.dir)
    _run_completion(committing_db, sent.id, store)
    _run_completion(committing_db, sent.id, store)  # a retry after success changes nothing

    envelope = owner.get(f"{ENVELOPES}/{sent.id}").json()
    assert envelope["status"] == "completed"
    with committing_db.unit_of_work() as uow:
        row = uow.session.execute(
            text(
                "SELECT workspace_id, signed_blob, signed_sha256, certificate_blob, "
                "certificate_sha256 FROM envelopes WHERE id = :e"
            ),
            {"e": sent.id},
        ).one()
        mail = uow.session.execute(
            text(
                "SELECT m.id, m.to_address, count(a.position) AS files FROM email_messages m "
                "LEFT JOIN email_attachments a ON a.email_id = m.id "
                "WHERE m.category = 'sign_completed' AND m.dedupe_key LIKE :k "
                "GROUP BY m.id, m.to_address"
            ),
            {"k": f"sign_completed:{sent.id}:%"},
        ).all()
    with store.open(BlobRef.from_token(row.workspace_id, row.signed_blob)) as source:
        signed = source.read()
    with store.open(BlobRef.from_token(row.workspace_id, row.certificate_blob)) as source:
        proof = source.read()
    assert hashlib.sha256(signed).digest() == bytes(row.signed_sha256)
    assert hashlib.sha256(proof).digest() == bytes(row.certificate_sha256)

    document = pymupdf.open(stream=signed, filetype="pdf")
    words = "".join(document[i].get_text() for i in range(document.page_count))
    assert "Founder" in words and "Rosa Hale" in words and "12-3456789" in words  # everything
    certificate = pymupdf.open(stream=proof, filetype="pdf")
    proof_words = "".join(certificate[i].get_text() for i in range(certificate.page_count))
    proof_words = proof_words.replace("ﬁ", "fi")
    assert hashlib.sha256(signed).hexdigest() in proof_words.replace("\n", "")
    assert "Signora sign-in" in proof_words and "Maya Chen" in proof_words

    told = {m.to_address: m.files for m in mail}
    assert told.keys() >= {company.email, "desk@firm.example", "records@firm.example"}
    assert set(told.values()) == {2}  # the document and its certificate, once each

    outbox = Outbox()
    deliver = make_deliver(
        transport_factory=lambda: outbox, daily_limit=lambda: 10_000, blob_store=lambda: store
    )
    one = next(m for m in mail if m.to_address == "records@firm.example")
    with committing_db.unit_of_work() as uow:
        job = uow.session.execute(
            text(
                "INSERT INTO jobs (kind, status, attempts, payload) VALUES "
                "('email.deliver', 'running', 1, CAST(:p AS jsonb)) RETURNING id"
            ),
            {"p": json.dumps({"message_id": str(one.id)})},
        ).scalar_one()
    deliver(JobContext(job, "email.deliver", {"message_id": str(one.id)}, {}, 1, committing_db))
    (email,) = outbox.sent
    assert [a.filename for a in email.attachments] == [
        f"{envelope['title']}.pdf",
        f"{envelope['title']} - certificate of completion.pdf",
    ]
    assert email.attachments[0].data == signed


def test_the_sender_downloads_the_document_its_certificate_or_both(
    owner: TestClient,
    run: Callable[..., None],
    detect: Callable[..., None],
    company: Account,
    browser: TestClient,
    committing_db: Database,
    settings: Settings,
) -> None:
    sent = signable_envelope(owner, run, detect, company, settings=NO_CODE)
    assert owner.get(f"{ENVELOPES}/{sent.id}/download").status_code == 409  # not completed yet
    _signers_done(browser, sent)
    _countersign(owner, sent)
    _run_completion(committing_db, sent.id, LocalBlobStore(settings.blob_store.dir))

    # The colleague who countersigned keeps their page: done, completed, and the copy to download.
    firm = str(sent.recipient("countersigner")["id"])
    assert owner.get(f"{SIGN}/{firm}").json()["next"] == "done"
    done = owner.get(f"{SIGN}/{firm}/done").json()
    assert (done["completed"], done["verified_by"]) == (True, "signora_sign_in")
    mine = owner.get(f"{SIGN}/{firm}/completed", params={"part": "certificate"})
    assert mine.status_code == 200 and mine.content.startswith(b"%PDF")

    pages: dict[str, int] = {}
    for part in ("document", "certificate", "combined"):
        answer = owner.get(f"{ENVELOPES}/{sent.id}/download", params={"part": part})
        assert answer.status_code == 200, answer.text
        assert answer.headers["content-type"] == "application/pdf"
        pages[part] = pymupdf.open(stream=answer.content, filetype="pdf").page_count
    assert pages["combined"] == pages["document"] + pages["certificate"]
