"""A company's website and logo (Company logo LLD §9)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from signora.kernel.blobstore import blob_store_from_settings
from signora.kernel.config import DatabaseSettings, LogoSettings, Settings
from signora.kernel.db import Database
from signora.kernel.jobs import JobContext, JobRegistry
from signora.modules.identity_access import company_logo, logo_dev
from signora.modules.identity_access import jobs as identity_jobs
from signora.modules.identity_access import signup as signup_service
from signora.modules.identity_access.domain.website import InvalidWebsiteError, company_domain
from tests.modules.identity_access.conftest import (
    PASSWORD,
    idempotency_key,
    latest_email,
    link_token,
    log_in,
    unique_email,
)
from tests.support.workers import running_worker

KEY = SecretStr("sk_test")
PNG = logo_dev.PNG_SIGNATURE + b"\x00" * 64
DOWNLOAD = "https://img.logo.dev/assets/brand_1.png?signature=abc"


# --- the website field -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "domain"),
    [
        ("scoutboard.com", "scoutboard.com"),
        ("  https://www.ScoutBoard.com/about?x=1  ", "scoutboard.com"),
        ("http://app.scoutboard.co.uk:8080", "app.scoutboard.co.uk"),
        ("scoutboard.com.", "scoutboard.com"),
        ("münchen.de", "xn--mnchen-3ya.de"),
    ],
)
def test_a_website_is_kept_as_its_domain(typed: str, domain: str) -> None:
    assert company_domain(typed) == domain


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "localhost",
        "http://localhost:3000",
        "127.0.0.1",
        "http://[::1]/",
        "10.0.0.5",
        "ftp://scoutboard.com",
        "javascript:alert(1)",
        "https://user:pass@scoutboard.com",
        "scout board.com",
        "-scoutboard.com",
        "scoutboard.123",
        "https://scoutboard.com:99999",
        "a" * 64 + ".com",
        "x." * 130 + "com",
    ],
)
def test_anything_but_a_public_host_name_is_refused(typed: str) -> None:
    with pytest.raises(InvalidWebsiteError):
        company_domain(typed)


# --- logo.dev ----------------------------------------------------------------------------------


def logo_dev_answering(
    api: Callable[[httpx.Request], httpx.Response],
    download: Callable[[httpx.Request], httpx.Response] | None = None,
    seen: list[httpx.Request] | None = None,
) -> httpx.Client:
    def route(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.host == "api.logo.dev":
            return api(request)
        assert download is not None, f"unexpected download from {request.url}"
        return download(request)

    return httpx.Client(transport=httpx.MockTransport(route))


def found(url: str = DOWNLOAD) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _: httpx.Response(200, json={"data": {"url": url, "etag": "etag-1"}})


def png(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})


def test_the_logo_is_asked_for_by_domain_with_the_secret_key_and_downloaded_for_a_dark_header() -> (
    None
):
    seen: list[httpx.Request] = []

    logo = logo_dev.find_logo(
        "scoutboard.com", secret_key=KEY, client=logo_dev_answering(found(), png, seen)
    )

    assert logo == logo_dev.Logo(png=PNG, etag="etag-1")
    asked, downloaded = seen
    assert asked.url.params["domain"] == "scoutboard.com"
    assert asked.headers["Authorization"] == "Bearer sk_test"
    assert downloaded.url.host == "img.logo.dev"
    assert downloaded.url.params["signature"] == "abc"  # the signed link is kept as given
    assert (downloaded.url.params["format"], downloaded.url.params["theme"]) == ("png", "dark")
    assert "Authorization" not in downloaded.headers  # the secret key goes to the API only


@pytest.mark.parametrize("status", [404, 400, 401, 402, 403])
def test_no_logo_or_a_refusal_retrying_cannot_fix_means_no_logo(status: int) -> None:
    client = logo_dev_answering(lambda _: httpx.Response(status, json={}))
    assert logo_dev.find_logo("scoutboard.com", secret_key=KEY, client=client) is None


@pytest.mark.parametrize("status", [202, 429, 500, 503])
def test_indexing_rate_limits_and_outages_are_tried_again_later(status: int) -> None:
    client = logo_dev_answering(lambda _: httpx.Response(status, json={}))
    with pytest.raises(logo_dev.LogoDevUnavailableError):
        logo_dev.find_logo("scoutboard.com", secret_key=KEY, client=client)


def test_an_unreachable_logo_dev_is_tried_again_later() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(logo_dev.LogoDevUnavailableError):
        logo_dev.find_logo("scoutboard.com", secret_key=KEY, client=logo_dev_answering(unreachable))


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example/logo.png",
        "https://logo.dev.evil.example/logo.png",
        "http://img.logo.dev/logo.png",
        "https://127.0.0.1/logo.png",
    ],
)
def test_a_download_link_anywhere_but_logo_dev_over_https_is_never_fetched(link: str) -> None:
    seen: list[httpx.Request] = []
    client = logo_dev_answering(found(link), seen=seen)

    assert logo_dev.find_logo("scoutboard.com", secret_key=KEY, client=client) is None
    assert [r.url.host for r in seen] == ["api.logo.dev"]


@pytest.mark.parametrize(
    "download",
    [
        lambda _: httpx.Response(200, content=b"<svg onload=alert(1)>"),
        lambda _: httpx.Response(200, content=PNG + b"\x00" * logo_dev.MAX_LOGO_BYTES),
        lambda _: httpx.Response(404),
        lambda _: httpx.Response(302, headers={"Location": "http://169.254.169.254/"}),
    ],
    ids=["not-a-png", "too-large", "gone", "redirect"],
)
def test_a_download_that_is_not_a_small_png_is_not_kept(
    download: Callable[[httpx.Request], httpx.Response],
) -> None:
    client = logo_dev_answering(found(), download)
    assert logo_dev.find_logo("scoutboard.com", secret_key=KEY, client=client) is None


def test_an_answer_without_a_link_is_no_logo() -> None:
    client = logo_dev_answering(lambda _: httpx.Response(200, json={"data": {}}))
    assert logo_dev.find_logo("scoutboard.com", secret_key=KEY, client=client) is None


# --- sign-up, the job and the header -----------------------------------------------------------


@pytest.fixture
def signup_worker(committing_db: Database, test_db_settings: DatabaseSettings) -> Iterator[None]:
    """Sends the sign-up emails; the logo look-up stays queued for the test to run."""
    registry = JobRegistry()
    identity_jobs.register(registry)
    only_signups = JobRegistry()
    only_signups.register(registry.get(signup_service.SIGNUP_REQUEST))
    with running_worker(committing_db, test_db_settings, only_signups):
        yield


def sign_up(client: TestClient, db: Database, **overrides: Any) -> tuple[str, Any]:
    email = unique_email("logo")
    client.post("/api/v1/auth/signup", json={"email": email})
    token = link_token(latest_email(db, email), "/signup/verify")
    body = {"token": token, "workspace_name": "ScoutBoard", "name": "Ana", "password": PASSWORD}
    body.update(overrides)
    response = client.post("/api/v1/auth/signup/complete", json=body, headers=idempotency_key())
    return email, response


def workspace_of(db: Database, email: str) -> Any:
    with db.unit_of_work() as uow:
        return uow.session.execute(
            text(
                "SELECT w.id, w.website, w.logo_sha256, w.logo_etag FROM workspaces w "
                "JOIN users u ON u.workspace_id = w.id WHERE u.email = :e"
            ),
            {"e": email},
        ).one()


def logo_jobs(db: Database, workspace_id: uuid.UUID) -> list[Any]:
    with db.unit_of_work() as uow:
        return list(
            uow.session.execute(
                text("SELECT payload FROM jobs WHERE kind = :k AND payload->>'workspace_id' = :w"),
                {"k": company_logo.FIND_LOGO, "w": str(workspace_id)},
            ).scalars()
        )


def run_logo_job(
    db: Database, settings: Settings, workspace_id: uuid.UUID, client: httpx.Client
) -> None:
    """Claim this workspace's queued look-up, as a worker would, and run it against ``client``
    instead of logo.dev."""
    with db.unit_of_work() as uow:
        job = uow.session.execute(
            text(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, "
                "lease_expires_at = now() + interval '1 minute' "
                "WHERE kind = :k AND status = 'queued' AND payload->>'workspace_id' = :w "
                "RETURNING id, kind, payload, meta, attempts"
            ),
            {"k": company_logo.FIND_LOGO, "w": str(workspace_id)},
        ).one()
    context = JobContext(job.id, job.kind, job.payload, job.meta, job.attempts, db)
    company_logo.find_and_keep(
        context,
        settings=LogoSettings(secret_key=KEY),
        store=blob_store_from_settings(settings.blob_store),
        client=client,
    )


@pytest.mark.usefixtures("signup_worker")
def test_a_website_given_at_sign_up_is_kept_as_its_domain_and_its_logo_is_looked_up(
    client: TestClient, committing_db: Database
) -> None:
    email, response = sign_up(client, committing_db, website="https://www.ScoutBoard.com/team")

    assert response.status_code == 201
    workspace = workspace_of(committing_db, email)
    assert workspace.website == "scoutboard.com"
    assert logo_jobs(committing_db, workspace.id) == [
        {"workspace_id": str(workspace.id), "domain": "scoutboard.com"}
    ]


@pytest.mark.usefixtures("signup_worker")
@pytest.mark.parametrize("website", [None, "", "   "])
def test_the_website_is_optional(
    client: TestClient, committing_db: Database, website: str | None
) -> None:
    email, response = sign_up(client, committing_db, website=website)

    assert response.status_code == 201
    workspace = workspace_of(committing_db, email)
    assert workspace.website is None
    assert logo_jobs(committing_db, workspace.id) == []
    log_in(client, email)
    assert client.get("/api/v1/me").json()["workspace"]["logo_url"] is None


@pytest.mark.usefixtures("signup_worker")
def test_a_website_that_is_not_one_is_a_field_error_and_creates_nothing(
    client: TestClient, committing_db: Database
) -> None:
    email, response = sign_up(client, committing_db, website="http://localhost:8080")

    assert response.status_code == 422
    assert [e["field"] for e in response.json()["errors"]] == ["website"]
    with committing_db.unit_of_work() as uow:
        assert (
            uow.session.execute(
                text("SELECT count(*) FROM users WHERE email = :e"), {"e": email}
            ).scalar_one()
            == 0
        )


@pytest.mark.usefixtures("signup_worker")
def test_a_found_logo_is_kept_and_shown_to_the_companys_members_only(
    client: TestClient,
    make_client: Callable[..., TestClient],
    committing_db: Database,
    settings: Settings,
) -> None:
    email, _ = sign_up(client, committing_db, website="scoutboard.com")
    run_logo_job(
        committing_db,
        settings,
        workspace_of(committing_db, email).id,
        logo_dev_answering(found(), png),
    )

    workspace = workspace_of(committing_db, email)
    assert workspace.logo_etag == "etag-1"
    log_in(client, email)
    logo_url = client.get("/api/v1/me").json()["workspace"]["logo_url"]
    assert logo_url == f"/api/v1/workspace/logo?v={workspace.logo_sha256[:16]}"
    logo = client.get(logo_url)
    assert logo.status_code == 200
    assert logo.content == PNG
    assert logo.headers["content-type"] == "image/png"
    assert "immutable" in logo.headers["cache-control"]
    with make_client() as stranger:
        assert stranger.get(logo_url).status_code == 401


@pytest.mark.usefixtures("signup_worker")
def test_when_no_logo_is_found_the_company_keeps_showing_its_name(
    client: TestClient, committing_db: Database, settings: Settings
) -> None:
    email, _ = sign_up(client, committing_db, website="scoutboard.com")
    run_logo_job(
        committing_db,
        settings,
        workspace_of(committing_db, email).id,
        logo_dev_answering(lambda _: httpx.Response(404)),
    )

    assert workspace_of(committing_db, email).logo_sha256 is None
    log_in(client, email)
    me = client.get("/api/v1/me").json()
    assert (me["workspace"]["name"], me["workspace"]["logo_url"]) == ("ScoutBoard", None)
    assert client.get("/api/v1/workspace/logo").status_code == 404


@pytest.mark.usefixtures("signup_worker")
def test_a_logo_found_for_a_website_since_changed_is_not_kept(
    client: TestClient, committing_db: Database, settings: Settings
) -> None:
    email, _ = sign_up(client, committing_db, website="scoutboard.com")
    workspace = workspace_of(committing_db, email)
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text("UPDATE workspaces SET website = 'other.com' WHERE id = :w"), {"w": workspace.id}
        )

    run_logo_job(committing_db, settings, workspace.id, logo_dev_answering(found(), png))

    assert workspace_of(committing_db, email).logo_sha256 is None


def test_without_a_key_the_look_up_does_nothing() -> None:
    context = JobContext(
        uuid.uuid4(),
        company_logo.FIND_LOGO,
        {"workspace_id": str(uuid.uuid4()), "domain": "a.io"},
        {},
        1,
        database=None,  # type: ignore[arg-type]  # never reached
    )
    company_logo.find_and_keep(
        context,
        settings=LogoSettings(secret_key=None),
        store=None,  # type: ignore[arg-type]  # never reached
        client=logo_dev_answering(lambda _: pytest.fail("logo.dev was called")),
    )
