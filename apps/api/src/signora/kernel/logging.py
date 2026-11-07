"""Structured logging (backbone LLD §7.2).

JSON lines to stdout; a readable console format in development on a terminal. Request and job
context (``request_id``, ``workspace_id``, ``user_id``, ``job_id``, ``job_kind``) is bound through
context variables, never passed by hand. A redaction processor masks secret-looking fields by exact
name or suffix, never by substring, so metrics such as ``status_code`` or ``prompt_tokens`` survive.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from signora.kernel.config import AppSettings

REDACTED = "**********"
SECRET_NAMES = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "otp",
        "otp_code",
        "cookie",
        "set_cookie",
        "authorization",
        "signature_image",
    }
)
SECRET_SUFFIXES = ("_password", "_secret", "_api_key")


def _is_secret(key: str) -> bool:
    name = key.lower().replace("-", "_")
    return name in SECRET_NAMES or name.endswith(SECRET_SUFFIXES)


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: REDACTED if _is_secret(str(k)) else _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(item) for item in value]
    return value


def redact_secrets(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """structlog processor: mask secret-looking fields at any depth."""
    for key in list(event_dict):
        event_dict[key] = REDACTED if _is_secret(key) else _redact_value(event_dict[key])
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        redact_secrets,
    ]


def configure_logging(settings: AppSettings, *, force_json: bool = False) -> None:
    """Configure structlog and route standard-library logging (uvicorn, alembic) through it."""
    use_console = not force_json and settings.env == "development" and sys.stdout.isatty()
    renderer: Processor = (
        structlog.dev.ConsoleRenderer()
        if use_console
        else structlog.processors.JSONRenderer(sort_keys=True)
    )

    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_shared_processors(),
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)
    # Our access middleware logs requests with route templates; uvicorn's own access log would
    # log raw paths (which can contain signing tokens), so it is silenced.
    logging.getLogger("uvicorn.access").disabled = True
    # Alembic logs its migration context at INFO on every revision check; keep only warnings.
    logging.getLogger("alembic").setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger


def bind_context(**values: Any) -> None:
    """Attach values (e.g. request_id, job_id) to every log line in the current context."""
    structlog.contextvars.bind_contextvars(**values)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


def current_context() -> MutableMapping[str, Any]:
    return structlog.contextvars.get_contextvars()
