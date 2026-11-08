"""Serving the working copy to the viewer and the original as a download (Phase 4 LLD §5.2)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.modules.documents.conftest import Account, create_department, log_in, new_document
from tests.support.files import docx_bytes, pdf_bytes, risky_pdf

DOCUMENTS = "/api/v1/documents"


def _urls(document: dict[str, object]) -> tuple[str, str]:
    version = document["versions"][0]  # type: ignore[index]
    base = f"{DOCUMENTS}/{document['id']}/versions/{version['id']}"
    return f"{base}/pdf", f"{base}/original"


def test_the_working_copy_is_shown_inline_in_parts(
    owner: TestClient, run: Callable[..., None]
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], risky_pdf(), name="Retainer").json()
    run(document["versions"][0]["id"])
    pdf_url, _ = _urls(document)

    whole = owner.get(pdf_url)
    part = owner.get(pdf_url, headers={"Range": "bytes=0-99"})

    assert whole.status_code == 200
    assert whole.headers["content-type"] == "application/pdf"
    assert whole.headers["content-disposition"] == "inline; filename*=utf-8''Retainer%20v1.pdf"
    assert whole.headers["cache-control"] == "private, no-store"
    assert whole.headers["x-content-type-options"] == "nosniff"
    assert whole.headers["accept-ranges"] == "bytes"
    assert b"/JavaScript" not in whole.content  # the cleaned copy, never the upload
    assert part.status_code == 206
    assert part.content == whole.content[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{len(whole.content)}"


def test_a_version_not_processed_yet_has_nothing_to_show(owner: TestClient) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    response = owner.get(_urls(document)[0])
    assert (response.status_code, response.json()["code"]) == (409, "version-not-ready")


def test_the_original_is_always_a_download_of_the_exact_upload(owner: TestClient) -> None:
    department = create_department(owner)
    data = docx_bytes()
    document = new_document(owner, department["id"], data).json()

    response = owner.get(_urls(document)[1])

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-disposition"].startswith('attachment; filename="Letter.pdf"')
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_viewers_download_and_other_companies_cannot(
    owner: TestClient,
    run: Callable[..., None],
    make_client: Callable[..., TestClient],
    company: Account,
    add_member: Callable[..., Account],
    make_workspace: Callable[..., Account],
) -> None:
    department = create_department(owner)
    document = new_document(owner, department["id"], pdf_bytes()).json()
    run(document["versions"][0]["id"])
    pdf_url, original_url = _urls(document)
    viewer = add_member(company, role="read")
    with make_client() as theirs:
        log_in(theirs, viewer.email)
        assert theirs.get(pdf_url).status_code == 200
        assert theirs.get(original_url).status_code == 200
    stranger = make_workspace(workspace_name="Baker & Co")
    with make_client() as theirs:
        log_in(theirs, stranger.email)
        assert theirs.get(pdf_url).status_code == 404
        assert theirs.get(original_url).status_code == 404
