"""Spooling a request body to disk under a hard limit (Phase 4 LLD §2.2)."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from signora.kernel.errors import PayloadTooLarge
from signora.kernel.spool import spool_body

LIMIT = 1000


def _app(received: list[Path]) -> FastAPI:
    app = FastAPI()

    @app.post("/in")
    async def receive(request: Request) -> dict[str, int]:
        try:
            path = await spool_body(request, max_bytes=LIMIT)
        except PayloadTooLarge:
            return {"refused": 1}
        received.append(path)
        return {"size": path.stat().st_size}

    return app


def _chunks(total: int) -> Iterator[bytes]:
    for _ in range(total // 100):
        yield b"x" * 100


def test_a_body_within_the_limit_lands_in_a_file() -> None:
    received: list[Path] = []
    with TestClient(_app(received)) as client:
        assert client.post("/in", content=b"y" * LIMIT).json() == {"size": LIMIT}
    assert received[0].read_bytes() == b"y" * LIMIT
    received[0].unlink()


def test_a_streamed_body_without_a_length_stops_at_the_limit_and_leaves_no_file() -> None:
    received: list[Path] = []
    before = set(Path(tempfile.gettempdir()).glob("signora-upload-*"))
    with TestClient(_app(received)) as client:
        response = client.post("/in", content=_chunks(LIMIT * 3))  # chunked: no Content-Length
    assert response.json() == {"refused": 1}
    assert received == []
    assert set(Path(tempfile.gettempdir()).glob("signora-upload-*")) == before


def test_a_declared_length_over_the_limit_is_refused_before_reading() -> None:
    with TestClient(_app([])) as client:
        response = client.post("/in", content=b"z" * (LIMIT + 1))
    assert response.json() == {"refused": 1}
