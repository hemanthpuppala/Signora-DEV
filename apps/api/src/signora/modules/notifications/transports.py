"""Email transports (Phase 2 LLD §1a.3): SendGrid's v3 API, SMTP (Gmail) and Mailpit.

A transport sends one message and either returns the provider's message id or raises
``TransientEmailError`` (retry later) or ``PermanentEmailError`` (retrying cannot help).
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Protocol

import httpx

from signora.kernel.config import EmailSettings

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
SEND_TIMEOUT_SECONDS = 15.0
_ERROR_DETAIL_MAX = 500


class EmailError(Exception):
    """Base class; the message is safe to log (never contains the body)."""


class TransientEmailError(EmailError):
    """The provider may accept the same message later (timeouts, throttling, 5xx, SMTP 4xx)."""


class PermanentEmailError(EmailError):
    """The provider refused the message for good (bad address, bad credentials, too large)."""


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str
    message_id: str  # our id, used as the SMTP Message-ID and SendGrid custom argument
    reply_to: str | None = None  # where a reply goes (a send's sender, Phase 7)


class Transport(Protocol):
    name: str

    def send(self, email: OutgoingEmail) -> str:
        """Send ``email``; returns the provider's message id."""
        ...


@dataclass(frozen=True)
class Sender:
    address: str
    name: str

    @property
    def domain(self) -> str:
        return self.address.rsplit("@", 1)[-1]


class SendGridTransport:
    """SendGrid v3 ``mail/send``. Click and open tracking are off: tracking rewrites links through
    SendGrid's redirector, which would expose sign-in tokens and drop the URL fragment."""

    name = "sendgrid"

    def __init__(self, *, api_key: str, sender: Sender, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._sender = sender
        self._client = client or httpx.Client(timeout=SEND_TIMEOUT_SECONDS)

    def send(self, email: OutgoingEmail) -> str:
        payload = {
            "personalizations": [{"to": [{"email": email.to}]}],
            "from": {"email": self._sender.address, "name": self._sender.name},
            "subject": email.subject,
            "content": [
                {"type": "text/plain", "value": email.text},
                {"type": "text/html", "value": email.html},
            ],
            "custom_args": {"signora_message_id": email.message_id},
            **({"reply_to": {"email": email.reply_to}} if email.reply_to else {}),
            "tracking_settings": {
                "click_tracking": {"enable": False, "enable_text": False},
                "open_tracking": {"enable": False},
                "subscription_tracking": {"enable": False},
            },
        }
        try:
            response = self._client.post(
                SENDGRID_URL,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as error:
            raise TransientEmailError(f"sendgrid unreachable: {type(error).__name__}") from None
        if response.is_success:
            return response.headers.get("X-Message-Id") or email.message_id
        detail = f"sendgrid answered {response.status_code}: {response.text[:_ERROR_DETAIL_MAX]}"
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientEmailError(detail)
        raise PermanentEmailError(detail)


class SmtpTransport:
    """SMTP with STARTTLS and login (Gmail app password), or plain SMTP for Mailpit."""

    def __init__(
        self,
        *,
        name: str,
        host: str,
        port: int,
        sender: Sender,
        starttls: bool,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.name = name
        self._host = host
        self._port = port
        self._sender = sender
        self._starttls = starttls
        self._username = username
        self._password = password

    def _message(self, email: OutgoingEmail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((self._sender.name, self._sender.address))
        message["To"] = email.to
        message["Subject"] = email.subject
        message["Date"] = formatdate(localtime=False, usegmt=True)
        message["Message-ID"] = make_msgid(idstring=email.message_id, domain=self._sender.domain)
        message["Auto-Submitted"] = "auto-generated"
        if email.reply_to:
            message["Reply-To"] = email.reply_to
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        return message

    def send(self, email: OutgoingEmail) -> str:
        message = self._message(email)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=SEND_TIMEOUT_SECONDS) as smtp:
                if self._starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if self._username and self._password:
                    smtp.login(self._username, self._password)
                smtp.send_message(message)
        except smtplib.SMTPRecipientsRefused as error:
            codes = [code for code, _ in error.recipients.values()]
            text = f"recipient refused ({codes})"
            if all(400 <= code < 500 for code in codes):
                raise TransientEmailError(text) from None
            raise PermanentEmailError(text) from None
        except smtplib.SMTPResponseException as error:
            text = f"smtp answered {error.smtp_code}"
            if 400 <= error.smtp_code < 500:
                raise TransientEmailError(text) from None
            raise PermanentEmailError(text) from None
        except (smtplib.SMTPException, OSError) as error:
            raise TransientEmailError(f"smtp unreachable: {type(error).__name__}") from None
        return str(message["Message-ID"])


def transport_from_settings(settings: EmailSettings) -> Transport:
    """The configured transport. Raises ``PermanentEmailError`` when email is not configured."""
    not_configured = PermanentEmailError(f"email provider {settings.provider!r} is not configured")
    if settings.from_address is None:
        raise not_configured
    sender = Sender(settings.from_address, settings.from_name)
    match settings.provider:
        case "sendgrid":
            if settings.sendgrid_api_key is None:
                raise not_configured
            return SendGridTransport(
                api_key=settings.sendgrid_api_key.get_secret_value(), sender=sender
            )
        case "smtp":
            if settings.smtp_username is None or settings.smtp_password is None:
                raise not_configured
            return SmtpTransport(
                name="smtp",
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=sender,
                starttls=settings.smtp_starttls,
                username=settings.smtp_username,
                password=settings.smtp_password.get_secret_value(),
            )
        case "mailpit":
            return SmtpTransport(
                name="mailpit",
                host=settings.mailpit_host,
                port=settings.mailpit_smtp_port,
                sender=sender,
                starttls=False,
            )
