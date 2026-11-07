"""API application tests: problem details, request ids, access log, health and meta (LLD §7)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, EmailStr
from sqlalchemy import Engine
from structlog.testing import capture_logs

from signora.entrypoints.api import create_app
from signora.kernel import errors
from signora.kernel.config import ApiSettings, DatabaseSettings, Settings, load_settings
from signora.kernel.health import Check, CheckFailedError
from signora.kernel.http import request_info


class _Payload(BaseModel):
    emails: list[EmailStr]


def _test_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/test/domain/{name}")
    def domain_error(name: str) -> None:
        error_types: dict[str, errors.DomainError] = {
            "not-found": errors.NotFound(),
            "conflict": errors.Conflict("already approved"),
            "forbidden": errors.PermissionDenied(),
            "unauthenticated": errors.Unauthenticated(),
            "rate-limited": errors.RateLimited(retry_after_seconds=30),
            "in-progress": errors.RequestInProgress(retry_after_seconds=1),
            "not-configured": errors.IntegrationNotConfigured("AI"),
        }
        raise error_types[name]

    @router.post("/api/v1/test/validate")
    def validate(payload: _Payload) -> dict[str, int]:
        return {"count": len(payload.emails)}

    @router.get("/api/v1/test/crash")
    def crash() -> None:
        raise RuntimeError("database password is hunter2")

    @router.get("/s/{token}")
    def signing_link(token: str) -> dict[str, bool]:
        return {"ok": bool(token)}

    return router


def _ok_checks(_: Settings, __: Engine) -> Sequence[Check]:
    return [Check("database", lambda: None)]


def _failing_checks(_: Settings, __: Engine) -> Sequence[Check]:
    def down() -> None:
        raise CheckFailedError("connection refused")

    return [Check("database", down), Check("gotenberg", lambda: None)]


@pytest.fixture
def settings(test_db_settings: DatabaseSettings) -> Settings:
    return load_settings().model_copy(update={"db": test_db_settings})


def _client(app: FastAPI) -> TestClient:
    app.include_router(_test_router())
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(settings: Settings, engine: Engine) -> TestClient:
    return _client(create_app(settings, engine=engine, checks_factory=_ok_checks))


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("not-found", 404, "not-found"),
        ("conflict", 409, "conflict"),
        ("forbidden", 403, "permission-denied"),
        ("unauthenticated", 401, "unauthenticated"),
        ("rate-limited", 429, "rate-limited"),
        ("in-progress", 409, "request-in-progress"),
        ("not-configured", 503, "integration-not-configured"),
    ],
)
def test_domain_errors_become_problem_details(
    client: TestClient, name: str, status: int, code: str
) -> None:
    response = client.get(f"/api/v1/test/domain/{name}")

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == code
    assert body["type"] == f"/problems/{code}"
    assert body["status"] == status
    assert body["instance"] == "/api/v1/test/domain/{name}"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_retry_after_header_is_sent(client: TestClient) -> None:
    assert client.get("/api/v1/test/domain/rate-limited").headers["Retry-After"] == "30"
    assert client.get("/api/v1/test/domain/in-progress").headers["Retry-After"] == "1"


def test_validation_errors_use_the_same_shape_with_field_paths(client: TestClient) -> None:
    response = client.post("/api/v1/test/validate", json={"emails": ["ok@example.com", "nope"]})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation-failed"
    assert [e["field"] for e in body["errors"]] == ["emails[1]"]
    assert body["detail"] == "1 field needs attention"


def test_unknown_route_is_a_problem_404(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "not-found"


def test_unexpected_error_returns_generic_500_and_logs_the_stack(client: TestClient) -> None:
    with capture_logs() as logs:
        response = client.get("/api/v1/test/crash")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal-error"
    assert "hunter2" not in response.text
    assert body["request_id"] == response.headers["X-Request-ID"]
    unhandled = next(e for e in logs if e["event"] == "http.unhandled_error")
    assert unhandled["exc_info"] is True
    access = next(e for e in logs if e["event"] == "http.request")
    assert access["status"] == 500


def test_access_log_uses_route_template_not_raw_path(client: TestClient) -> None:
    with capture_logs() as logs:
        client.get("/s/super-secret-signing-token")

    access = next(e for e in logs if e["event"] == "http.request")
    assert access["route"] == "/s/{token}"
    assert "super-secret-signing-token" not in repr(logs)


def test_request_id_is_generated_and_client_value_ignored_by_default(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "client-chosen-id-123"})

    assert response.headers["X-Request-ID"] != "client-chosen-id-123"
    assert len(response.headers["X-Request-ID"]) == 36  # UUID


def test_proxy_request_id_and_client_ip_are_trusted_when_configured(
    settings: Settings, engine: Engine
) -> None:
    trusted = settings.model_copy(
        update={"api": ApiSettings(threads=settings.api.threads, trust_proxy_headers=True)}
    )
    app = create_app(trusted, engine=engine, checks_factory=_ok_checks)

    @app.get("/api/v1/test/info")
    def info(request: Request) -> dict[str, str | None]:
        details = request_info(request)
        return {"request_id": details.request_id, "ip": details.ip}

    client = TestClient(app)
    response = client.get(
        "/api/v1/test/info",
        headers={"X-Request-ID": "caddy-0001-uuid", "X-Forwarded-For": "203.0.113.7, 10.0.0.2"},
    )

    assert response.headers["X-Request-ID"] == "caddy-0001-uuid"
    assert response.json() == {"request_id": "caddy-0001-uuid", "ip": "203.0.113.7"}
    malformed = client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id with spaces"})
    assert malformed.headers["X-Request-ID"] != "bad id with spaces"


@pytest.mark.parametrize(
    ("trust_proxy_headers", "headers"),
    [
        (True, {"X-Forwarded-For": "unknown"}),
        (True, {"X-Forwarded-For": "not-an-ip, 10.0.0.2"}),
        (False, {}),  # the test client's peer address is the name "testclient"
    ],
)
def test_client_ip_that_is_not_an_ip_is_stored_as_unknown(
    settings: Settings, engine: Engine, trust_proxy_headers: bool, headers: dict[str, str]
) -> None:
    configured = settings.model_copy(
        update={
            "api": ApiSettings(
                threads=settings.api.threads, trust_proxy_headers=trust_proxy_headers
            )
        }
    )
    app = create_app(configured, engine=engine, checks_factory=_ok_checks)

    @app.get("/api/v1/test/info")
    def info(request: Request) -> dict[str, str | None]:
        return {"ip": request_info(request).ip}

    response = TestClient(app).get("/api/v1/test/info", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ip": None}


VALID_BODY = {"name": "x", "emails": ["a@example.com"]}


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},  # a sibling subdomain is still another site's page
        {"Sec-Fetch-Site": "cross-site", "Origin": "https://hemanth.tail50655e.ts.net"},
        {"Origin": "https://evil.example"},  # an older browser without fetch metadata
    ],
)
def test_cross_site_state_changes_are_refused(
    client: TestClient, settings: Settings, headers: dict[str, str]
) -> None:
    response = client.post("/api/v1/test/validate", json=VALID_BODY, headers=headers)

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "cross-site-request"
    assert body["instance"] == "<unmatched>"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_same_origin_and_non_browser_requests_pass(client: TestClient, settings: Settings) -> None:
    public_origin = str(settings.app.public_base_url).rstrip("/")
    for headers in (
        {"Sec-Fetch-Site": "same-origin"},
        {"Sec-Fetch-Site": "none"},
        {"Origin": public_origin},
        {},  # curl, server-to-server: no browser, no CSRF
    ):
        response = client.post("/api/v1/test/validate", json=VALID_BODY, headers=headers)
        assert response.status_code != 403, headers


def test_safe_methods_and_non_api_paths_are_not_checked(client: TestClient) -> None:
    cross = {"Sec-Fetch-Site": "cross-site"}
    assert client.get("/api/v1/health/live", headers=cross).status_code == 200
    assert client.get("/s/some-token", headers=cross).status_code == 200


def test_live_and_meta(client: TestClient) -> None:
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    meta = client.get("/api/v1/meta").json()
    assert meta["version"] == "0.1.0"
    assert meta["commit"]
    assert meta["password_min_length"] == 12


def test_public_readiness_is_summary_only(settings: Settings, engine: Engine) -> None:
    client = TestClient(create_app(settings, engine=engine, checks_factory=_failing_checks))

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_internal_readiness_names_the_failed_check(settings: Settings, engine: Engine) -> None:
    client = TestClient(create_app(settings, engine=engine, checks_factory=_failing_checks))

    body = client.get("/internal/health/ready").json()

    by_name = {c["name"]: c for c in body["checks"]}
    assert body["status"] == "unavailable"
    assert by_name["database"]["status"] == "failed"
    assert by_name["database"]["message"] == "connection refused"
    assert by_name["gotenberg"]["status"] == "ok"
    assert {"ai", "email", "stripe"} <= by_name.keys()


def test_ready_is_200_when_checks_pass(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_document_is_served(client: TestClient) -> None:
    assert client.get("/api/v1/openapi.json").json()["info"]["title"] == "Signora API"


def test_openapi_declares_problem_details_and_typed_responses(client: TestClient) -> None:
    document = client.get("/api/v1/openapi.json").json()

    schemas = document["components"]["schemas"]
    assert {"ProblemDetails", "StatusResponse", "MetaResponse"} <= set(schemas)
    meta = document["paths"]["/api/v1/meta"]["get"]["responses"]
    assert {"200", "4XX", "422", "5XX"} <= set(meta)
    problem = meta["4XX"]["content"]["application/problem+json"]["schema"]
    assert problem == {"$ref": "#/components/schemas/ProblemDetails"}
    assert "/internal/health/ready" not in document["paths"]
