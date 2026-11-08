"""Word to PDF through Gotenberg (Phase 4 LLD §3.1).

Gotenberg runs without network access behind its gateway and converts one file at a time, queueing
the rest; its own request limit is 120 s (``--api-timeout``), which includes the queue wait. This
client waits a little longer, so Gotenberg's own answer arrives first.
"""

from __future__ import annotations

import httpx

CONVERT_PATH = "/forms/libreoffice/convert"
TIMEOUT = httpx.Timeout(130.0, connect=5.0)


class ConversionUnavailableError(Exception):
    """Gotenberg could not be reached, timed out or failed on its side: worth retrying."""


class ConversionRefusedError(Exception):
    """Gotenberg read the file and could not convert it: retrying will not help."""


def docx_to_pdf(base_url: str, data: bytes, *, client: httpx.Client | None = None) -> bytes:
    owned = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        response = http.post(
            f"{base_url}{CONVERT_PATH}",
            files={"files": ("document.docx", data, "application/octet-stream")},
        )
    except httpx.HTTPError as error:
        raise ConversionUnavailableError(type(error).__name__) from error
    finally:
        if owned:
            http.close()
    if response.status_code == 200:
        return response.content
    if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
        raise ConversionRefusedError(f"gotenberg answered {response.status_code}")
    raise ConversionUnavailableError(f"gotenberg answered {response.status_code}")
