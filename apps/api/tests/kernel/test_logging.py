"""Log redaction tests (backbone LLD §7.2)."""

from __future__ import annotations

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
