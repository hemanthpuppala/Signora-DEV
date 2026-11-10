"""A scripted AI for detection tests: answers from the fields listed in the real message."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from signora.modules.detection.ai import AiCall, AiError, Usage

Fields = list[tuple[str, str]]  # (id, kind shown in the message)
Script = Callable[[Fields], dict[str, Any]] | AiError

KINDS = {
    "text box": "text",
    "signature box": "signature",
    "checkbox": "checkbox",
    "radio group": "radio",
    "dropdown": "combobox",
    "list": "listbox",
    "blank line (no form field)": "blank",
}


def listed_fields(user_message: str) -> Fields:
    block = user_message.split("<fields>\n", 1)[1].split("\n</fields>", 1)[0]
    rows = [line.split(" | ") for line in block.splitlines() if line.strip()]
    return [(row[0], KINDS[row[1]]) for row in rows]


def plain_answer(fields: Fields) -> dict[str, Any]:
    """A sensible answer: signatures by the client, choices and values by the sender."""
    answered = []
    for field_id, kind in fields:
        holds, filled_by = {
            "signature": ("signature", "client"),
            "checkbox": ("checkbox", "client"),
            "radio": ("choice", "sender"),
            "combobox": ("choice", "sender"),
            "listbox": ("choice", "sender"),
        }.get(kind, ("text", "sender"))
        answered.append(
            {
                "id": field_id,
                "holds": holds,
                "format": None,
                "filled_by": filled_by,
                "label": f"Field {field_id}",
                "must_fill": True,
                "depends_on": None,
            }
        )
    return {
        "roles": [{"slug": "client", "kind": "signer"}],
        "fields": answered,
        "checkbox_groups": [],
        "extra_fields": [],
        "document": {
            "name": "Client engagement letter",
            "description": "An engagement letter between the firm and a client. The client signs.",
        },
    }


class FakeAssigner:
    """Each call takes the next script entry (an answer builder or an error), then plain answers."""

    def __init__(self, *script: Script) -> None:
        self.script = list(script)
        self.messages: list[list[dict[str, str]]] = []

    def assign(self, messages: list[dict[str, str]], answer: type[BaseModel]) -> AiCall:
        self.messages.append(messages)
        step = self.script.pop(0) if self.script else plain_answer
        if isinstance(step, AiError):
            raise step
        built = step(listed_fields(messages[1]["content"]))
        answer.model_validate(built)  # as the SDK's strict parsing would
        return AiCall(
            answer=built,
            content=json.dumps(built),
            request_id=f"fake-{len(self.messages)}",
            model="fake-model",
            latency_s=0.01,
            usage=Usage(input=1000, cached=0, output=200, reasoning=50),
        )
