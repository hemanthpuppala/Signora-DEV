"""PDF facts and the working copy (Phase 4 LLD §3.1-3.2), without a database."""

from __future__ import annotations

import re
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
    form_with_scripts,
    links_reaching_outside,
    pdf_bytes,
    pdf_with_scan,
    pdf_with_signature_block,
    risky_pdf,
)


def test_no_link_reaches_outside_the_document_however_it_is_written() -> None:
    """Review fix: a link opening another file (/GoToR), a launch chained after a safe link
    (/Next) and a launch kept as its own object all survived the working copy."""
    working = prepare(links_reaching_outside(), max_pages=200).pdf
    with pymupdf.open(stream=working, filetype="pdf") as document:
        objects = " ".join(document.xref_object(x) for x in range(1, document.xref_length()))
        assert "/Launch" not in objects
        assert "/GoToR" not in objects
        # No chain left: "/Next null" is the same as no entry.
        assert re.search(r"/Next\s*(<<|\[|\d+ 0 R)", objects) is None
        uris = [link.get("uri") for link in document.load_page(0).get_links()]
        assert "https://example.org" in uris  # an ordinary link stays


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


def test_the_working_copy_keeps_no_form_field_scripts_but_keeps_the_fields() -> None:
    """Phase 5 §2.1: field actions survived the first cleaning; a downloaded working copy opened in
    another reader would have run them."""
    original = form_with_scripts()
    with pymupdf.open(stream=original, filetype="pdf") as document:
        names = sorted(w.field_name for w in document.load_page(0).widgets())
    working = prepare(original, max_pages=200).pdf
    with pymupdf.open(stream=working, filetype="pdf") as document:
        actions = []
        for xref in range(1, document.xref_length()):
            if document.xref_get_key(xref, "AA")[0] != "null":
                actions.append((xref, "AA"))
            if document.xref_get_key(xref, "A/S")[1] == "/JavaScript":
                actions.append((xref, "A"))
            if document.xref_get_key(xref, "S")[1] == "/JavaScript":
                actions.append((xref, "S"))
        assert actions == []
        page = document.load_page(0)
        assert sorted(w.field_name for w in page.widgets()) == names  # every field kept
        assert [link["kind"] for link in page.get_links()] == [pymupdf.LINK_URI]  # kept, harmless


def test_scanned_pages_are_found_but_blank_pages_and_signature_blocks_are_not() -> None:
    assert prepare(pdf_with_scan([2, 3], pages=4), max_pages=200).pages_without_text == [2, 3]
    assert prepare(pdf_with_scan([], pages=3, blank=[2]), max_pages=200).pages_without_text == []
    assert prepare(pdf_with_signature_block(), max_pages=200).pages_without_text == []
