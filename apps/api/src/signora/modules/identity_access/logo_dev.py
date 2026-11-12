"""logo.dev's brand API: a company's logo by its domain (Company logo LLD §5). No database here.

Two steps, so a refresh downloads nothing when the logo is unchanged: ``look_up`` answers the
logo's version (``etag``) and a short-lived download link; ``download`` fetches the PNG from it,
sized for the header (logo.dev's self-hosting rule: keep the file, never the link).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from signora.kernel.logging import get_logger

log = get_logger("signora.identity")

API_URL = "https://api.logo.dev/v2/brands/logo"
DOWNLOAD_DOMAIN = "logo.dev"  # download links point at img.logo.dev; nothing else is fetched
LOGO_SIZE = 128  # pixels on the long side: the header shows it about 28 px tall, sharp at 2x+
MAX_LOGO_BYTES = 512 * 1024
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_NOT_NOW = frozenset({httpx.codes.TOO_MANY_REQUESTS})  # 202 is its own (indexing)


@dataclass(frozen=True)
class FoundLogo:
    link: httpx.URL
    etag: str


class LogoDevUnavailableError(RuntimeError):
    """logo.dev did not answer in time or cannot now (indexing the brand, rate limit, outage)."""


class LogoDevIndexingError(LogoDevUnavailableError):
    """202: logo.dev has not indexed the domain yet and has started to; asking again within
    seconds usually finds the logo (its docs: retry shortly)."""


def look_up(domain: str, *, secret_key: SecretStr, client: httpx.Client) -> FoundLogo | None:
    """The brand's logo version and download link, or ``None`` when there is none to show.

    Raises ``LogoDevUnavailableError`` when asking again later may succeed. A refusal asking again
    cannot fix (a bad or unpaid key) is logged and answered ``None``.
    """
    try:
        answer = client.get(
            API_URL,
            params={"domain": domain},
            headers={"Authorization": f"Bearer {secret_key.get_secret_value()}"},
        )
    except httpx.HTTPError as error:
        raise LogoDevUnavailableError(f"logo.dev unreachable: {type(error).__name__}") from error
    _raise_if_not_now(answer)
    if answer.status_code == httpx.codes.NOT_FOUND:
        return None
    if answer.status_code != httpx.codes.OK:
        log.warning("company_logo.refused", status=answer.status_code, domain=domain)
        return None
    try:
        data = answer.json()["data"]
        link, etag = httpx.URL(str(data["url"])), str(data["etag"])
    except (ValueError, KeyError, TypeError, httpx.InvalidURL):
        log.warning("company_logo.unreadable_answer", domain=domain)
        return None
    if link.scheme != "https" or not _is_logo_dev(link.host):
        log.warning("company_logo.unexpected_link", host=link.host, domain=domain)
        return None
    return FoundLogo(link=link, etag=etag)


def download(found: FoundLogo, *, client: httpx.Client) -> bytes | None:
    """The logo as a PNG for a dark background, read no further than ``MAX_LOGO_BYTES``;
    ``None`` when the file is not a small PNG. Raises ``LogoDevUnavailableError`` like
    ``look_up``."""
    sized = found.link.copy_merge_params({"format": "png", "size": LOGO_SIZE, "theme": "dark"})
    try:
        with client.stream("GET", sized) as answer:
            _raise_if_not_now(answer)
            if answer.status_code != httpx.codes.OK:
                return None
            body = bytearray()
            for chunk in answer.iter_bytes():
                body += chunk
                if len(body) > MAX_LOGO_BYTES:
                    return None
    except httpx.HTTPError as error:
        raise LogoDevUnavailableError(f"logo download failed: {type(error).__name__}") from error
    return bytes(body) if body.startswith(PNG_SIGNATURE) else None


def _raise_if_not_now(answer: httpx.Response) -> None:
    if answer.status_code == httpx.codes.ACCEPTED:
        raise LogoDevIndexingError("logo.dev answered 202: indexing the domain")
    if answer.status_code in _NOT_NOW or answer.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise LogoDevUnavailableError(f"logo.dev answered {answer.status_code}")


def _is_logo_dev(host: str) -> bool:
    return host == DOWNLOAD_DOMAIN or host.endswith(f".{DOWNLOAD_DOMAIN}")


def client() -> httpx.Client:
    """No redirects are followed: every request goes only where this module points it."""
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False)
