"""Receiving a large request body without holding it in memory (Phase 4 LLD §2.2).

``spool_body`` streams the raw body to a temporary file and stops the moment it passes the limit,
whatever ``Content-Length`` claimed. The caller owns the returned file and must delete it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import anyio
from starlette.requests import Request

from signora.kernel.errors import PayloadTooLarge


def _declared_length(request: Request) -> int | None:
    value = request.headers.get("content-length")
    if value is None or not value.isdigit():
        return None
    return int(value)


async def spool_body(request: Request, *, max_bytes: int) -> Path:
    """The request body in a new temporary file; ``PayloadTooLarge`` over ``max_bytes``."""
    declared = _declared_length(request)
    if declared is not None and declared > max_bytes:
        raise PayloadTooLarge(f"limit is {max_bytes} bytes")
    fd, name = tempfile.mkstemp(prefix="signora-upload-")
    os.close(fd)
    path = Path(name)
    size = 0
    try:
        async with await anyio.open_file(path, "wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_bytes:
                    raise PayloadTooLarge(f"limit is {max_bytes} bytes")
                if chunk:
                    await out.write(chunk)
    except BaseException:
        await anyio.Path(path).unlink(missing_ok=True)
        raise
    return path
