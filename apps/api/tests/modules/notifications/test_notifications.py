"""Email delivery tests (Phase 2 LLD topic 1a)."""

from __future__ import annotations

import json
import smtplib
import uuid
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from signora.kernel.config import DatabaseSettings, EmailSettings
from signora.kernel.db import Database
from signora.kernel.jobs import JobRegistry
from signora.modules.notifications import EmailAction, render_layout, send_email
from signora.modules.notifications import service as notifications
from signora.modules.notifications.transports import (
    OutgoingEmail,
    PermanentEmailError,
    Sender,
    SendGridTransport,
    SmtpTransport,
    TransientEmailError,
    transport_from_settings,
)
from tests.support.workers import running_worker, wait_until

MAILPIT_API = "http://127.0.0.1:8025/api/v1"
SENDER = Sender("noreply@signora.test", "Signora")


class FakeTransport:
    """Scripted outcomes apply only to the test's own message (``target``); any other queued
    message in the shared test database is simply accepted."""

    name = "fake"

    def __init__(self, *outcomes: Exception | None) -> None:
        self.outcomes = list(outcomes)
        self.sent: list[OutgoingEmail] = []
        self.target: str | None = None

    def send(self, email: OutgoingEmail) -> str:
        if email.message_id == self.target and self.outcomes:
            outcome = self.outcomes.pop(0)
            if outcome is not None:
                raise outcome
        self.sent.append(email)
        return f"provider-{email.message_id}"

    def sent_to_target(self) -> list[OutgoingEmail]:
        return [email for email in self.sent if email.message_id == self.target]


def queue(db: Database, **overrides: Any) -> uuid.UUID:
    values: dict[str, Any] = {
        "to": f"person-{uuid.uuid4().hex[:8]}@example.com",
        "subject": "Hello",
        "text": "Body with a secret link",
        "html": "<p>Body with a secret link</p>",
        "category": "test.hello",
    }
    values.update(overrides)
    with db.unit_of_work() as uow:
        message_id = send_email(uow, **values)
    assert message_id is not None
    return message_id


def message(db: Database, message_id: uuid.UUID) -> Any:
    with db.unit_of_work() as uow:
        return uow.session.execute(
            text("SELECT * FROM email_messages WHERE id = :id"), {"id": message_id}
        ).one()


@pytest.fixture
def delivering(committing_db: Database, test_db_settings: DatabaseSettings) -> Iterator[Any]:
    """Start a worker whose delivery job uses the given fake transport and daily limit."""

    workers: list[Any] = []

    def start(
        transport: FakeTransport, message_id: uuid.UUID, daily_limit: int = 1_000_000
    ) -> None:
        transport.target = str(message_id)
        reg = JobRegistry()
        notifications.register(
            reg, transport_factory=lambda: transport, daily_limit=lambda: daily_limit
        )
        context = running_worker(committing_db, test_db_settings, reg)
        context.__enter__()
        workers.append(context)

    yield start
    for context in workers:
        context.__exit__(None, None, None)


# --- layout ------------------------------------------------------------------------------------


def test_layout_escapes_caller_text_and_matches_the_text_part() -> None:
    email = render_layout(
        heading="Join <b>Acme</b>",
        paragraphs=["Rosa & Sam invited you.", "<script>alert(1)</script>"],
        action=EmailAction("Accept invitation", "https://signora.test/invite#abc"),
        footer="You received this because someone invited you.",
    )

    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html
    assert "Join &lt;b&gt;Acme&lt;/b&gt;" in email.html
    assert 'href="https://signora.test/invite#abc"' in email.html
    assert email.text.startswith("Join <b>Acme</b>\n")
    assert "Accept invitation: https://signora.test/invite#abc" in email.text
    assert "Rosa & Sam invited you." in email.text


# --- queueing ----------------------------------------------------------------------------------


def test_send_email_queues_the_message_and_its_job_together(db: Database) -> None:
    message_id = queue(db)

    with db.unit_of_work() as uow:
        jobs = uow.session.execute(
            text("SELECT payload FROM jobs WHERE dedupe_key = :k"), {"k": f"email:{message_id}"}
        ).all()
    assert jobs[0].payload == {"message_id": str(message_id)}
    assert message(db, message_id).status == "queued"


def test_nothing_is_sent_when_the_caller_rolls_back(db: Database) -> None:
    address = f"rolled-back-{uuid.uuid4().hex[:8]}@example.com"
    with pytest.raises(RuntimeError), db.unit_of_work() as uow:
        send_email(uow, to=address, subject="x", text="x", html="x", category="test")
        raise RuntimeError("the business action failed")

    with db.unit_of_work() as uow:
        count = uow.session.execute(
            text("SELECT count(*) FROM email_messages WHERE to_address = :a"), {"a": address}
        ).scalar_one()
    assert count == 0


def test_a_dedupe_key_queues_the_email_once(db: Database) -> None:
    key = f"welcome:{uuid.uuid4()}"
    first = queue(db, dedupe_key=key)
    with db.unit_of_work() as uow:
        second = send_email(
            uow, to="x@example.com", subject="x", text="x", html="x", category="t", dedupe_key=key
        )
    assert first is not None
    assert second is None


# --- delivery job ------------------------------------------------------------------------------


def test_delivery_marks_sent_and_purges_the_body(committing_db: Database, delivering: Any) -> None:
    transport = FakeTransport()
    message_id = queue(committing_db)
    delivering(transport, message_id)

    wait_until(lambda: message(committing_db, message_id).status == "sent")

    row = message(committing_db, message_id)
    assert (row.provider, row.provider_message_id, row.attempts) == (
        "fake",
        f"provider-{message_id}",
        1,
    )
    assert row.text_body is None and row.html_body is None
    assert [email.text for email in transport.sent_to_target()] == ["Body with a secret link"]


def test_permanent_failure_is_recorded_without_retrying(
    committing_db: Database, delivering: Any
) -> None:
    transport = FakeTransport(PermanentEmailError("sendgrid answered 400: bad address"))
    message_id = queue(committing_db)
    delivering(transport, message_id)

    wait_until(lambda: message(committing_db, message_id).status == "failed")

    row = message(committing_db, message_id)
    assert row.attempts == 1
    assert "400" in row.last_error
    assert row.text_body is None and row.html_body is None
    assert transport.sent_to_target() == []


@pytest.mark.usefixtures("no_backoff")
def test_transient_failures_are_retried_then_delivered(
    committing_db: Database, delivering: Any
) -> None:
    transport = FakeTransport(TransientEmailError("timeout"), TransientEmailError("429"))
    message_id = queue(committing_db)
    delivering(transport, message_id)

    wait_until(lambda: message(committing_db, message_id).status == "sent")

    assert message(committing_db, message_id).attempts == 3
    assert len(transport.sent_to_target()) == 1


@pytest.mark.usefixtures("no_backoff")
def test_transient_failures_end_as_failed_after_the_last_attempt(
    committing_db: Database, delivering: Any
) -> None:
    errors = [TransientEmailError("smtp answered 421")] * notifications.MAX_ATTEMPTS
    transport = FakeTransport(*errors)
    message_id = queue(committing_db)
    delivering(transport, message_id)

    wait_until(lambda: message(committing_db, message_id).status == "failed", timeout=20)

    row = message(committing_db, message_id)
    assert row.attempts == notifications.MAX_ATTEMPTS
    assert row.text_body is None


def test_the_daily_limit_defers_delivery_without_using_attempts(
    committing_db: Database, delivering: Any
) -> None:
    transport = FakeTransport()
    message_id = queue(committing_db)
    delivering(transport, message_id, daily_limit=0)

    def deferred() -> Any:
        with committing_db.unit_of_work() as uow:
            return uow.session.execute(
                text(
                    "SELECT run_at - now() AS wait FROM jobs "
                    "WHERE dedupe_key LIKE :k AND status = 'queued'"
                ),
                {"k": f"email:{message_id}:deferred:%"},
            ).one_or_none()

    wait_until(lambda: deferred() is not None)

    row = message(committing_db, message_id)
    assert row.status == "queued"  # not failed: it waits for capacity
    assert row.attempts == 0
    assert row.text_body is not None  # the body is kept for the later send
    assert row.last_error == "waiting for daily email capacity"
    assert deferred().wait.total_seconds() > 50 * 60  # no capacity today: try again in an hour
    assert transport.sent_to_target() == []


# --- SendGrid ----------------------------------------------------------------------------------


def outgoing() -> OutgoingEmail:
    return OutgoingEmail(
        to="rosa@example.com",
        subject="Verify",
        text="Open https://signora.test/signup/verify#token",
        html="<a href='https://signora.test/signup/verify#token'>Verify</a>",
        message_id="m-1",
    )


def sendgrid(handler: Any) -> SendGridTransport:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SendGridTransport(api_key="SG.test", sender=SENDER, client=client)


def test_sendgrid_sends_with_link_tracking_off() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, headers={"X-Message-Id": "sg-123"})

    assert sendgrid(handler).send(outgoing()) == "sg-123"

    request = seen[0]
    body = json.loads(request.content)
    assert request.headers["Authorization"] == "Bearer SG.test"
    assert body["personalizations"] == [{"to": [{"email": "rosa@example.com"}]}]
    assert body["from"] == {"email": "noreply@signora.test", "name": "Signora"}
    tracking = body["tracking_settings"]
    assert tracking["click_tracking"] == {"enable": False, "enable_text": False}
    assert tracking["open_tracking"] == {"enable": False}
    assert [part["type"] for part in body["content"]] == ["text/plain", "text/html"]
    assert "reply_to" not in body  # only when the email has one


def test_sendgrid_sets_reply_to_the_sender() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202)

    sendgrid(handler).send(replace(outgoing(), reply_to="rosa.hale@firm.example"))

    assert json.loads(seen[0].content)["reply_to"] == {"email": "rosa.hale@firm.example"}


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (429, TransientEmailError),
        (500, TransientEmailError),
        (503, TransientEmailError),
        (400, PermanentEmailError),
        (401, PermanentEmailError),
        (403, PermanentEmailError),
        (413, PermanentEmailError),
    ],
)
def test_sendgrid_classifies_failures(status: int, error: type[Exception]) -> None:
    transport = sendgrid(lambda request: httpx.Response(status, text="nope"))
    with pytest.raises(error, match=str(status)):
        transport.send(outgoing())


def test_sendgrid_network_errors_are_transient_and_never_include_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(TransientEmailError) as excinfo:
        sendgrid(handler).send(outgoing())
    assert "SG.test" not in str(excinfo.value)


# --- SMTP --------------------------------------------------------------------------------------


def test_smtp_delivers_to_mailpit() -> None:
    to = f"smtp-{uuid.uuid4().hex[:8]}@example.com"
    transport = SmtpTransport(
        name="mailpit", host="127.0.0.1", port=1025, sender=SENDER, starttls=False
    )

    message_id = transport.send(
        OutgoingEmail(
            to=to,
            subject="Mailpit check",
            text="plain",
            html="<b>html</b>",
            message_id="m",
            reply_to="rosa.hale@firm.example",
        )
    )

    search = httpx.get(f"{MAILPIT_API}/search", params={"query": f"to:{to}"}).json()
    found = search["messages"][0]
    assert found["Subject"] == "Mailpit check"
    assert found["ReplyTo"] == [{"Name": "", "Address": "rosa.hale@firm.example"}]
    assert found["From"] == {"Name": "Signora", "Address": "noreply@signora.test"}
    assert message_id.endswith("@signora.test>")


class _FailingSmtp:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def __call__(self, *args: Any, **kwargs: Any) -> _FailingSmtp:
        return self

    def __enter__(self) -> _FailingSmtp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def send_message(self, message: Any) -> None:
        raise self.error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (smtplib.SMTPRecipientsRefused({"a@x": (550, b"no such user")}), PermanentEmailError),
        (smtplib.SMTPRecipientsRefused({"a@x": (450, b"mailbox busy")}), TransientEmailError),
        (smtplib.SMTPResponseException(421, b"try later"), TransientEmailError),
        (smtplib.SMTPResponseException(554, b"rejected"), PermanentEmailError),
        (smtplib.SMTPServerDisconnected("gone"), TransientEmailError),
        (TimeoutError("slow"), TransientEmailError),
    ],
)
def test_smtp_classifies_failures(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: type[Exception]
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", _FailingSmtp(error))
    transport = SmtpTransport(name="smtp", host="h", port=25, sender=SENDER, starttls=False)

    with pytest.raises(expected):
        transport.send(outgoing())


# --- configuration -----------------------------------------------------------------------------


def email_settings(**overrides: Any) -> EmailSettings:
    values: dict[str, Any] = {
        "provider": "mailpit",
        "sendgrid_api_key": None,
        "mailpit_host": "127.0.0.1",
        "mailpit_smtp_port": 1025,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_starttls": True,
        "smtp_username": None,
        "smtp_password": None,
        "from_address": "noreply@signora.test",
        "from_name": "Signora",
        "daily_limit": 450,
    }
    values.update(overrides)
    return EmailSettings(**values)


def test_transport_follows_the_configured_provider() -> None:
    assert transport_from_settings(email_settings()).name == "mailpit"
    assert (
        transport_from_settings(email_settings(provider="sendgrid", sendgrid_api_key="SG.k")).name
        == "sendgrid"
    )
    smtp = email_settings(
        provider="smtp",
        smtp_username="me@gmail.com",
        smtp_password="app-pw",  # noqa: S106 - test value
    )
    assert transport_from_settings(smtp).name == "smtp"


@pytest.mark.parametrize(
    "settings",
    [
        {"from_address": None},
        {"provider": "sendgrid"},
        {"provider": "smtp", "smtp_username": "me@gmail.com"},
    ],
)
def test_unconfigured_email_is_a_permanent_failure(settings: dict[str, Any]) -> None:
    with pytest.raises(PermanentEmailError, match="not configured"):
        transport_from_settings(email_settings(**settings))


def test_the_default_transport_is_built_once_per_process() -> None:
    first = notifications._default_transport()
    assert notifications._default_transport() is first  # one client, one connection pool
