"""PDF facts and the working copy (Phase 4 LLD §3.1-3.2), without a database."""

from __future__ import annotations

import time

import pymupdf
import pytest

from signora.modules.documents.pdf import (
    DamagedPdfError,
    PasswordRequiredError,
    TooManyPagesError,
    needs_password,
    prepare,
    unlock,
)
from tests.support.files import (
    encrypted_pdf,
    pdf_bytes,
    pdf_with_scan,
    pdf_with_signature_block,
    risky_pdf,
)


def test_pages_are_measured_as_displayed() -> None:
    prepared = prepare(pdf_bytes(2), max_pages=200)
    assert len(prepared.pages) == 2
    assert (prepared.pages[0].width, prepared.pages[0].height, prepared.pages[0].rotation) == (
        595.0,
        842.0,
        0,
    )
    assert prepared.pages_without_text == []


def test_two_hundred_pages_pass_quickly_and_two_hundred_and_one_do_not() -> None:
    started = time.monotonic()
    prepared = prepare(pdf_bytes(200), max_pages=200)
    assert time.monotonic() - started < 30  # NFR-DOC2
    assert len(prepared.pages) == 200
    with pytest.raises(TooManyPagesError) as refused:
        prepare(pdf_bytes(201), max_pages=200)
    assert refused.value.pages == 201


def test_a_damaged_pdf_is_reported() -> None:
    with pytest.raises(DamagedPdfError):
        prepare(b"%PDF-1.7\nnot really a pdf", max_pages=200)


def test_a_password_protected_pdf_waits_and_opens_only_with_its_password() -> None:
    locked = encrypted_pdf("open-sesame")
    assert needs_password(locked)
    with pytest.raises(PasswordRequiredError):
        prepare(locked, max_pages=200)
    assert unlock(locked, "wrong") is None
    opened = unlock(locked, "open-sesame")
    assert opened is not None
    assert not needs_password(opened)
    assert len(prepare(opened, max_pages=200).pages) == 1


def test_edit_restrictions_alone_are_removed_without_asking() -> None:
    restricted = encrypted_pdf("")  # an owner password only
    assert not needs_password(restricted)
    working = prepare(restricted, max_pages=200).pdf
    with pymupdf.open(stream=working, filetype="pdf") as document:
        assert not document.is_encrypted


def test_the_working_copy_has_nothing_that_runs_but_keeps_form_fields() -> None:
    working = prepare(risky_pdf(), max_pages=200).pdf
    with pymupdf.open(stream=working, filetype="pdf") as document:
        assert document.embfile_count() == 0
        assert document.xref_get_key(document.pdf_catalog(), "OpenAction")[0] == "null"
        page = document.load_page(0)
        assert all(link["kind"] != pymupdf.LINK_LAUNCH for link in page.get_links())
        assert [w.field_name for w in page.widgets()] == ["client_name"]
    assert b"/JavaScript" not in working


def test_scanned_pages_are_found_but_blank_pages_and_signature_blocks_are_not() -> None:
    assert prepare(pdf_with_scan([2, 3], pages=4), max_pages=200).pages_without_text == [2, 3]
    assert prepare(pdf_with_scan([], pages=3, blank=[2]), max_pages=200).pages_without_text == []
    assert prepare(pdf_with_signature_block(), max_pages=200).pages_without_text == []
