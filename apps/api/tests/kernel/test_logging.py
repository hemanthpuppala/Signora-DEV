"""Log redaction tests (backbone LLD §7.2)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from signora.kernel.logging import REDACTED, redact_secrets


def _redact(event: dict[str, Any]) -> dict[str, Any]:
    return dict(redact_secrets(None, "info", event))


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "token",
        "access_token",
        "api_key",
        "otp",
        "otp_code",
        "cookie",
        "Authorization",
        "set-cookie",
        "smtp_password",
        "webhook_secret",
        "stripe_api_key",
        "signature_image",
    ],
)
def test_secret_names_and_suffixes_are_masked(key: str) -> None:
    assert _redact({key: "sensitive"})[key] == REDACTED


@pytest.mark.parametrize(
    "key", ["status_code", "postal_code", "code", "prompt_tokens", "completion_tokens", "tokenizer"]
)
def test_metrics_and_codes_stay_visible(key: str) -> None:
    assert _redact({key: 42})[key] == 42


def test_nested_values_are_masked_at_any_depth() -> None:
    event = {"headers": {"Authorization": "Bearer x", "accept": "json"}, "items": [{"otp": "1"}]}

    redacted = _redact(event)

    assert redacted["headers"] == {"Authorization": REDACTED, "accept": "json"}
    assert redacted["items"] == [{"otp": REDACTED}]


def test_configured_logging_emits_redacted_json_lines(tmp_path: Path) -> None:
    """Runs in a subprocess because logging configuration is process-global."""
    script = (
        "import logging\n"
        "from signora.kernel.config import load_settings\n"
        "from signora.kernel.logging import configure_logging, get_logger, bind_context\n"
        "configure_logging(load_settings().app, force_json=True)\n"
        "bind_context(request_id='req-1')\n"
        "get_logger('t').info('user.login', password='hunter2', status_code=200)\n"
        "logging.getLogger('uvicorn.error').info('server started')\n"
        "logging.getLogger('alembic.runtime').info('noise')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, cwd=tmp_path
    )
    lines = [json.loads(line) for line in result.stdout.splitlines()]

    app_line = next(line for line in lines if line["event"] == "user.login")
    assert app_line["password"] == REDACTED
    assert app_line["status_code"] == 200
    assert app_line["request_id"] == "req-1"
    assert app_line["level"] == "info"
    assert app_line["ts"].endswith("Z")
    assert any(line["event"] == "server started" for line in lines)  # stdlib routed through
    assert not any(line["event"] == "noise" for line in lines)  # alembic INFO suppressed
    assert "hunter2" not in result.stdout
