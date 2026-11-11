"""The certificate of completion (Phase 8 LLD §11): each person's events, their signature as
signed, the fingerprints, the disclosure they accepted; over as many pages as it takes."""

from __future__ import annotations

import uuid

import pymupdf

from signora.modules.rendering import Certificate, Copy, Signature, Signed, certificate_pdf

DRAWN = Signature(
    "drawn", None, None, [[(100, 200), (500, 260), (900, 180)]], "0123456789abcdef", "Drawn"
)
TYPED = Signature("typed", "Rosa Hale", "allura", None, "fedcba9876543210", "Typed, Allura")


def _person(role: str, name: str, mark: Signature, verified: str) -> Signed:
    return Signed(
        role=role,
        name=name,
        email=f"{name.split()[0].lower()}@example.com",
        verified_by=verified,
        signature=mark,
        initials=None,
        ip="203.0.113.7",
        sent="Nov 10, 2026 at 8:05 PM PST",
        viewed="Nov 10, 2026 at 8:09 PM PST",
        signed="Nov 10, 2026 at 8:14 PM PST",
        consented="Nov 10, 2026 at 8:07 PM PST",
        disclosure_version="esign-disclosure-v1",
    )


def _data(people: list[Signed]) -> Certificate:
    return Certificate(
        envelope_id=uuid.UUID("0193a5f2-0000-7000-8000-000000000001"),
        title="Mutual NDA · Maya Chen",
        template="Mutual NDA",
        pages=2,
        signatures=2,
        initials=0,
        sent_by="Rosa Hale (rosa@haleward.example)",
        time_zone="America/Los_Angeles",
        people=people,
        copies=[Copy("Records", "records@firm.example", "Nov 10, 2026 at 8:20 PM PST")],
        summary=[
            ("Sent", "Nov 10, 2026 at 8:05 PM PST"),
            ("Completed", "Nov 10, 2026 at 8:20 PM PST"),
        ],
        original_sha256="a" * 64,
        completed_sha256="b" * 64,
        disclosures={
            "esign-disclosure-v1": [("A paper copy", "Ask rosa@haleward.example. There is no fee.")]
        },
    )


def _text(pdf: bytes) -> tuple[pymupdf.Document, str]:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    words = "".join(doc[i].get_text() for i in range(doc.page_count))
    return doc, words.replace("ﬁ", "fi").replace("ﬂ", "fl")  # ligatures read as letters


def test_it_says_who_signed_how_they_proved_it_and_what_was_signed() -> None:
    doc, words = _text(
        certificate_pdf(
            _data(
                [
                    _person(
                        "Signer · Client", "Maya Chen", DRAWN, "Email code to m•••@example.com"
                    ),
                    _person("Countersigner · Firm", "Rosa Hale", TYPED, "Signora sign-in"),
                ]
            )
        )
    )

    assert "Certificate of completion" in words
    assert "0193A5F2-0000-7000-8000-000000000001" in words
    for expected in ("Maya Chen", "Rosa Hale", "Signora sign-in", "203.0.113.7", "Typed, Allura"):
        assert expected in words
    assert "0123456789ABCDEF" in words and "FEDCBA9876543210" in words
    assert "a" * 64 in words and "b" * 64 in words
    assert "esign-disclosure-v1" in words and "There is no fee." in words
    assert sum(len(doc[i].get_images()) for i in range(doc.page_count)) == 2  # each signature


def test_a_long_certificate_runs_over_pages() -> None:
    people = [_person("Signer", f"Person {n}", DRAWN, "Email link") for n in range(25)]

    doc, words = _text(certificate_pdf(_data(people)))

    assert doc.page_count > 2
    assert "Person 0" in words and "Person 24" in words
