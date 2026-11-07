"""Route handlers are plain ``def`` (backbone LLD §6.3a, ADR B-1).

FastAPI runs ``def`` handlers in its thread pool; an ``async def`` handler that touches the database
(synchronous SQLAlchemy) would block the event loop for every request. The check reads the source,
so it covers every module's routers without relying on FastAPI's internal route classes.
"""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "signora"
HTTP_METHOD_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options", "api_route"}

# Reviewed ``async def`` handlers that do no blocking I/O: "file.py:function" -> reason.
ALLOWED_ASYNC_HANDLERS: dict[str, str] = {}


def async_route_handlers(source: str, filename: str) -> list[str]:
    """Names (``file:function``) of ``async def`` functions decorated as HTTP routes."""
    found = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            func = call.func if call else decorator
            if isinstance(func, ast.Attribute) and func.attr in HTTP_METHOD_DECORATORS:
                found.append(f"{filename}:{node.name}")
                break
    return found


def test_checker_finds_an_async_route_handler() -> None:
    source = """
@router.get("/a")
def plain(): ...

@router.post("/b", status_code=201)
async def slow(): ...

@app.api_route("/c", methods=["GET"])
async def other(): ...

async def helper(): ...
"""
    assert async_route_handlers(source, "x.py") == ["x.py:slow", "x.py:other"]


def test_every_route_handler_is_a_plain_function() -> None:
    offenders = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        offenders += [
            name
            for name in async_route_handlers(source, relative)
            if name not in ALLOWED_ASYNC_HANDLERS
        ]

    assert offenders == [], (
        "route handlers must be plain `def` (LLD §6.3a); an `async def` handler that does no "
        f"blocking I/O must be added to ALLOWED_ASYNC_HANDLERS with a reason: {offenders}"
    )
