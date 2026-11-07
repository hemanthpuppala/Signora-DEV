"""Canonical JSON: stable bytes for hashing (idempotency fingerprints, audit hash chains).

Keys sorted, no insignificant whitespace, UTF-8 — in the spirit of RFC 8785. Callers must not pass
floating-point numbers where byte stability across a database round trip matters.
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
