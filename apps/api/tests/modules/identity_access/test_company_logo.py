"""A company's website and logo (Company logo LLD §9).

These tests never reach logo.dev: its answers come from ``httpx.MockTransport``, and the app runs
without a key unless a test gives it ``KEY``.
"""

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
from signora.kernel.config import DatabaseSettings, LogoSettings, Settings, load_settings
from signora.kernel.db import Database
from signora.kernel.jobs import JobContext, JobRegistry
from signora.modules.identity_access import company_logo, logo_dev
from signora.modules.identity_access import jobs as identity_jobs
from signora.modules.identity_access import signup as signup_service
from signora.modules.identity_access.domain.website import InvalidWebsiteError, company_domain
from tests.modules.identity_access.conftest import (
    PASSWORD,
    Account,
    csrf_headers,
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
        if download is None:
            pytest.fail(f"unexpected download from {request.url}")
        return download(request)

    return httpx.Client(transport=httpx.MockTransport(route))


def found(url: str = DOWNLOAD, etag: str = "etag-1") -> Callable[[httpx.Request], httpx.Response]:
    return lambda _: httpx.Response(200, json={"data": {"url": url, "etag": etag}})


def png(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})


def answering(status: int) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _: httpx.Response(status, json={})


def timing_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("logo.dev is slow", request=request)


def test_the_logo_is_asked_for_by_domain_with_the_secret_key_and_downloaded_for_a_dark_header() -> (
    None
):
    seen: list[httpx.Request] = []
    client = logo_dev_answering(found(), png, seen)

    logo = logo_dev.look_up("scoutboard.com", secret_key=KEY, client=client)
    assert logo is not None
    assert logo.etag == "etag-1"
    assert logo_dev.download(logo, client=client) == PNG

    asked, downloaded = seen
    assert asked.url.params["domain"] == "scoutboard.com"
    assert asked.headers["Authorization"] == "Bearer sk_test"
    assert downloaded.url.host == "img.logo.dev"
    assert downloaded.url.params["signature"] == "abc"  # the signed link is kept as given
    assert (downloaded.url.params["format"], downloaded.url.params["theme"]) == ("png", "dark")
    assert "Authorization" not in downloaded.headers  # the secret key goes to the API only


@pytest.mark.parametrize("status", [404, 400, 401, 402, 403])
def test_no_logo_or_a_refusal_asking_again_cannot_fix_means_no_logo(status: int) -> None:
    client = logo_dev_answering(answering(status))
    assert logo_dev.look_up("scoutboard.com", secret_key=KEY, client=client) is None


@pytest.mark.parametrize(
    "api",
    [answering(202), answering(429), answering(500), answering(503), timing_out],
    ids=["indexing", "rate-limited", "error", "down", "timeout"],
)
def test_indexing_rate_limits_outages_and_timeouts_mean_not_now(
    api: Callable[[httpx.Request], httpx.Response],
) -> None:
    with pytest.raises(logo_dev.LogoDevUnavailableError):
        logo_dev.look_up("scoutboard.com", secret_key=KEY, client=logo_dev_answering(api))


def test_a_download_that_times_out_means_not_now() -> None:
    client = logo_dev_answering(found(), timing_out)
    logo = logo_dev.look_up("scoutboard.com", secret_key=KEY, client=client)
    assert logo is not None
    with pytest.raises(logo_dev.LogoDevUnavailableError):
        logo_dev.download(logo, client=client)


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example/logo.png",
        "https://logo.dev.evil.example/logo.png",
        "http://img.logo.dev/logo.png",
        "https://127.0.0.1/logo.png",
    ],
)
def test_a_download_link_anywhere_but_logo_dev_over_https_is_refused(link: str) -> None:
    seen: list[httpx.Request] = []
    client = logo_dev_answering(found(link), seen=seen)

    assert logo_dev.look_up("scoutboard.com", secret_key=KEY, client=client) is None
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
    logo = logo_dev.look_up("scoutboard.com", secret_key=KEY, client=client)
    assert logo is not None
    assert logo_dev.download(logo, client=client) is None


def test_an_answer_without_a_link_is_no_logo() -> None:
    client = logo_dev_answering(lambda _: httpx.Response(200, json={"data": {}}))
    assert logo_dev.look_up("scoutboard.com", secret_key=KEY, client=client) is None


# --- sign-up, the look-up job and the header ---------------------------------------------------


@pytest.fixture
def settings(test_db_settings: DatabaseSettings) -> Settings:
    """The app without a logo.dev key (whatever .env holds); ``with_key`` adds one."""
    return load_settings().model_copy(
        update={"db": test_db_settings, "logo": LogoSettings(secret_key=None)}
    )


@pytest.fixture
def with_key(settings: Settings) -> Settings:
    return settings.model_copy(update={"logo": LogoSettings(secret_key=KEY)})


@pytest.fixture
def signup_worker(committing_db: Database, test_db_settings: DatabaseSettings) -> Iterator[None]:
    """Sends the sign-up emails; logo look-ups stay queued for the test to run."""
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
                "SELECT w.id, w.website, w.logo_sha256, w.logo_bytes, w.logo_etag, "
                "extract(epoch FROM w.logo_check_due_at - now()) AS due_in "
                "FROM workspaces w JOIN users u ON u.workspace_id = w.id WHERE u.email = :e"
            ),
            {"e": email},
        ).one()


def queued_look_ups(db: Database, workspace_id: uuid.UUID) -> int:
    with db.unit_of_work() as uow:
        return int(
            uow.session.execute(
                text(
                    "SELECT count(*) FROM jobs WHERE kind = :k AND status = 'queued' "
                    "AND payload->>'workspace_id' = :w"
                ),
                {"k": company_logo.FIND_LOGO, "w": str(workspace_id)},
            ).scalar_one()
        )


def claim_look_up(db: Database, workspace_id: uuid.UUID) -> JobContext:
    """This workspace's queued look-up, claimed as a worker would."""
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
    return JobContext(job.id, job.kind, job.payload, job.meta, job.attempts, db)


def run_look_up(
    db: Database, settings: Settings, workspace_id: uuid.UUID, client: httpx.Client
) -> None:
    """Run this workspace's queued look-up against ``client`` instead of logo.dev."""
    company_logo.find_and_keep(
        claim_look_up(db, workspace_id),
        settings=LogoSettings(secret_key=KEY),
        store=blob_store_from_settings(settings.blob_store),
        client=client,
    )


def plan_now(db: Database, workspace_id: uuid.UUID) -> None:
    with db.unit_of_work() as uow:
        company_logo.plan_check(uow.session, workspace_id, queue=True)


def run_sweep(db: Database, settings: LogoSettings) -> None:
    with db.unit_of_work() as uow:
        job_id = uow.session.execute(
            text(
                "INSERT INTO jobs (kind, payload, status, attempts, lease_expires_at) "
                "VALUES (:k, '{}', 'running', 1, now() + interval '1 minute') RETURNING id"
            ),
            {"k": company_logo.SWEEP},
        ).scalar_one()
    company_logo.sweep(JobContext(job_id, company_logo.SWEEP, {}, {}, 1, db), settings=settings)


HOUR, DAY = 3600, 86400


def assert_due_in(workspace: Any, seconds: int) -> None:
    assert workspace.due_in == pytest.approx(seconds, abs=60)


@pytest.mark.usefixtures("signup_worker")
def test_a_website_given_at_sign_up_is_kept_as_its_domain_and_its_logo_looked_up_at_once(
    make_client: Callable[..., TestClient], committing_db: Database, with_key: Settings
) -> None:
    with make_client(with_key) as client:
        email, response = sign_up(client, committing_db, website="https://www.ScoutBoard.com/team")

    assert response.status_code == 201
    workspace = workspace_of(committing_db, email)
    assert workspace.website == "scoutboard.com"
    assert_due_in(workspace, 0)
    assert queued_look_ups(committing_db, workspace.id) == 1


@pytest.mark.usefixtures("signup_worker")
def test_without_a_key_the_look_up_waits_for_the_sweep_once_there_is_one(
    client: TestClient, committing_db: Database
) -> None:
    email, _ = sign_up(client, committing_db, website="scoutboard.com")
    workspace = workspace_of(committing_db, email)
    assert queued_look_ups(committing_db, workspace.id) == 0  # nothing to ask without a key

    run_sweep(committing_db, LogoSettings(secret_key=None))
    assert queued_look_ups(committing_db, workspace.id) == 0

    run_sweep(committing_db, LogoSettings(secret_key=KEY))  # the key was added
    run_sweep(committing_db, LogoSettings(secret_key=KEY))  # and the sweep runs again
    assert queued_look_ups(committing_db, workspace.id) == 1


@pytest.mark.usefixtures("signup_worker")
@pytest.mark.parametrize("website", [None, "", "   "])
def test_the_website_is_optional(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    with_key: Settings,
    website: str | None,
) -> None:
    with make_client(with_key) as client:
        email, response = sign_up(client, committing_db, website=website)
        assert response.status_code == 201
        log_in(client, email)
        assert client.get("/api/v1/me").json()["workspace"]["logo_url"] is None

    workspace = workspace_of(committing_db, email)
    assert (workspace.website, workspace.due_in) == (None, None)
    assert queued_look_ups(committing_db, workspace.id) == 0


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
    make_client: Callable[..., TestClient],
    committing_db: Database,
    settings: Settings,
    with_key: Settings,
) -> None:
    with make_client(with_key) as client:
        email, _ = sign_up(client, committing_db, website="scoutboard.com")
        workspace_id = workspace_of(committing_db, email).id
        run_look_up(committing_db, settings, workspace_id, logo_dev_answering(found(), png))

        workspace = workspace_of(committing_db, email)
        assert workspace.logo_etag == "etag-1"
        assert_due_in(workspace, 30 * DAY)  # a refresh in a month
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
def test_a_refresh_downloads_nothing_while_the_logo_is_unchanged_and_the_new_one_when_it_changed(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    settings: Settings,
    with_key: Settings,
) -> None:
    with make_client(with_key) as client:
        email, _ = sign_up(client, committing_db, website="scoutboard.com")
    workspace_id = workspace_of(committing_db, email).id
    run_look_up(committing_db, settings, workspace_id, logo_dev_answering(found(), png))
    first = workspace_of(committing_db, email)

    plan_now(committing_db, workspace_id)
    run_look_up(committing_db, settings, workspace_id, logo_dev_answering(found()))  # no download
    unchanged = workspace_of(committing_db, email)
    assert unchanged.logo_sha256 == first.logo_sha256
    assert_due_in(unchanged, 30 * DAY)

    new_png = PNG + b"new"
    plan_now(committing_db, workspace_id)
    run_look_up(
        committing_db,
        settings,
        workspace_id,
        logo_dev_answering(found(etag="etag-2"), lambda _: httpx.Response(200, content=new_png)),
    )
    changed = workspace_of(committing_db, email)
    assert (changed.logo_etag, changed.logo_bytes) == ("etag-2", len(new_png))


@pytest.mark.usefixtures("signup_worker")
@pytest.mark.parametrize(
    ("api", "again"),
    [
        (answering(404), 7 * DAY),
        (answering(401), 7 * DAY),
        (answering(202), HOUR),
        (answering(503), HOUR),
        (timing_out, HOUR),
    ],
    ids=["no-logo", "bad-key", "indexing", "down", "timeout"],
)
def test_without_a_logo_the_company_keeps_its_name_and_logo_dev_is_asked_again_later(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    settings: Settings,
    with_key: Settings,
    api: Callable[[httpx.Request], httpx.Response],
    again: int,
) -> None:
    with make_client(with_key) as client:
        email, _ = sign_up(client, committing_db, website="scoutboard.com")
        workspace_id = workspace_of(committing_db, email).id
        run_look_up(committing_db, settings, workspace_id, logo_dev_answering(api))  # never raises

        workspace = workspace_of(committing_db, email)
        assert workspace.logo_sha256 is None
        assert_due_in(workspace, again)
        log_in(client, email)
        me = client.get("/api/v1/me").json()
        assert (me["workspace"]["name"], me["workspace"]["logo_url"]) == ("ScoutBoard", None)
        assert client.get("/api/v1/workspace/logo").status_code == 404


@pytest.mark.usefixtures("signup_worker")
def test_a_logo_found_for_a_website_since_changed_is_not_kept(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    settings: Settings,
    with_key: Settings,
) -> None:
    with make_client(with_key) as client:
        email, _ = sign_up(client, committing_db, website="scoutboard.com")
    workspace_id = workspace_of(committing_db, email).id
    context = claim_look_up(committing_db, workspace_id)

    def changed_meanwhile(request: httpx.Request) -> httpx.Response:
        with committing_db.unit_of_work() as uow:
            uow.session.execute(
                text("UPDATE workspaces SET website = 'other.com' WHERE id = :w"),
                {"w": workspace_id},
            )
        return png(request)

    company_logo.find_and_keep(
        context,
        settings=LogoSettings(secret_key=KEY),
        store=blob_store_from_settings(settings.blob_store),
        client=logo_dev_answering(found(), changed_meanwhile),
    )

    assert workspace_of(committing_db, email).logo_sha256 is None


@pytest.mark.usefixtures("signup_worker")
def test_a_logo_file_missing_from_the_store_shows_the_name_and_is_fetched_again(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    settings: Settings,
    with_key: Settings,
) -> None:
    with make_client(with_key) as client:
        email, _ = sign_up(client, committing_db, website="scoutboard.com")
        workspace_id = workspace_of(committing_db, email).id
        run_look_up(committing_db, settings, workspace_id, logo_dev_answering(found(), png))
        with committing_db.unit_of_work() as uow:  # as if the file were lost
            uow.session.execute(
                text("UPDATE workspaces SET logo_sha256 = :s WHERE id = :w"),
                {"s": "0" * 64, "w": workspace_id},
            )
        log_in(client, email)
        logo_url = client.get("/api/v1/me").json()["workspace"]["logo_url"]

        assert client.get(logo_url).status_code == 404
        assert client.get("/api/v1/me").json()["workspace"]["logo_url"] is None
        assert_due_in(workspace_of(committing_db, email), 0)
        assert queued_look_ups(committing_db, workspace_id) == 1


def test_the_sweep_queues_each_due_look_up_once(
    committing_db: Database, make_workspace: Callable[..., Account]
) -> None:
    account = make_workspace()
    with committing_db.unit_of_work() as uow:
        uow.session.execute(
            text(
                "UPDATE workspaces SET website = 'scoutboard.com', "
                "logo_check_due_at = now() - interval '1 minute' WHERE id = :w"
            ),
            {"w": account.workspace_id},
        )

    run_sweep(committing_db, LogoSettings(secret_key=KEY))
    run_sweep(committing_db, LogoSettings(secret_key=KEY))

    assert queued_look_ups(committing_db, account.workspace_id) == 1


# --- the website in Settings -------------------------------------------------------------------


def put_website(client: TestClient, website: str | None) -> Any:
    return client.put(
        "/api/v1/workspace/website", json={"website": website}, headers=csrf_headers(client)
    )


def test_the_owner_sets_changes_and_removes_the_website_and_a_new_one_drops_the_old_logo(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    make_workspace: Callable[..., Account],
    with_key: Settings,
) -> None:
    owner = make_workspace(workspace_name="ScoutBoard")
    with committing_db.unit_of_work() as uow:  # a logo found for an older website
        uow.session.execute(
            text(
                "UPDATE workspaces SET website = 'old.com', logo_sha256 = :s, logo_bytes = 1 "
                "WHERE id = :w"
            ),
            {"s": "a" * 64, "w": owner.workspace_id},
        )
    with make_client(with_key) as client:
        log_in(client, owner.email)

        answer = put_website(client, "https://www.ScoutBoard.com")
        assert answer.status_code == 200
        assert (answer.json()["website"], answer.json()["logo_url"]) == ("scoutboard.com", None)
        workspace = workspace_of(committing_db, owner.email)
        assert (workspace.website, workspace.logo_sha256) == ("scoutboard.com", None)
        assert queued_look_ups(committing_db, owner.workspace_id) == 1
        assert client.get("/api/v1/me").json()["workspace"]["website"] == "scoutboard.com"

        assert put_website(client, None).json()["website"] is None
        workspace = workspace_of(committing_db, owner.email)
        assert (workspace.website, workspace.due_in) == (None, None)

        refused = put_website(client, "localhost")
        assert refused.status_code == 422
        assert [e["field"] for e in refused.json()["errors"]] == ["website"]

    with committing_db.unit_of_work() as uow:
        recorded = uow.session.execute(
            text(
                "SELECT action FROM audit_events WHERE workspace_id = :w "
                "AND action = 'workspace.website_changed'"
            ),
            {"w": owner.workspace_id},
        ).all()
    assert len(recorded) == 2


def test_only_the_owner_changes_the_website(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    make_workspace: Callable[..., Account],
    add_member: Callable[..., Account],
) -> None:
    owner = make_workspace()
    editor = add_member(owner, role="read_write")
    with make_client() as client:
        log_in(client, editor.email)
        assert put_website(client, "scoutboard.com").status_code == 403
    assert workspace_of(committing_db, owner.email).website is None


@pytest.mark.usefixtures("signup_worker")
def test_a_look_up_queued_before_the_key_was_removed_asks_nothing_and_waits_a_day(
    make_client: Callable[..., TestClient],
    committing_db: Database,
    settings: Settings,
    with_key: Settings,
) -> None:
    with make_client(with_key) as client:
        email, _ = sign_up(client, committing_db, website="scoutboard.com")
    workspace_id = workspace_of(committing_db, email).id

    company_logo.find_and_keep(
        claim_look_up(committing_db, workspace_id),
        settings=LogoSettings(secret_key=None),
        store=blob_store_from_settings(settings.blob_store),
        client=logo_dev_answering(lambda _: pytest.fail("logo.dev was called")),
    )

    assert_due_in(workspace_of(committing_db, email), DAY)
