"""The AI call behind an interface (Phase 5 LLD §3.1, §1.1).

``Assigner`` is what the detection stages need: messages and the answer model in, the parsed answer
and the call's facts out. ``OpenAIAssigner`` talks to any OpenAI-compatible provider with strict
structured output; tests use their own ``Assigner``. Every provider failure becomes one of the
detection failure codes; logs carry tokens and latency, never the document's text.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import openai
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from signora.kernel.config import AISettings
from signora.kernel.logging import get_logger

log = get_logger("signora.detection")

FailureCode = Literal["ai_not_configured", "ai_unavailable", "detection_failed"]
PASSING_RETRIES = 2  # 429, 5xx, timeouts and dropped connections, with the SDK's backoff (§1.2)


class AiError(Exception):
    """The call could not give an answer; ``code`` is the version's failure code (§1.1)."""

    def __init__(self, code: FailureCode, reason: str) -> None:
        super().__init__(reason)
        self.code: FailureCode = code


@dataclass(frozen=True)
class Usage:
    input: int
    cached: int
    output: int
    reasoning: int


@dataclass(frozen=True)
class AiCall:
    answer: dict[str, Any]  # the parsed answer, as JSON
    content: str  # the model's message as sent back, for the repair round
    request_id: str
    model: str
    latency_s: float
    usage: Usage


class Assigner(Protocol):
    def assign(self, messages: list[dict[str, str]], answer: type[BaseModel]) -> AiCall: ...


class OpenAIAssigner:
    """One strict structured-output call per ``assign``: no tools, no images, nothing kept by the
    provider (``store: false``)."""

    def __init__(
        self, settings: AISettings, *, http_client: openai.DefaultHttpxClient | None = None
    ) -> None:
        self._settings = settings
        self._client = (
            OpenAI(
                api_key=settings.api_key.get_secret_value(),
                base_url=str(settings.base_url),
                timeout=settings.timeout_seconds,
                max_retries=PASSING_RETRIES,
                http_client=http_client,
            )
            if settings.api_key is not None
            else None
        )

    def assign(self, messages: list[dict[str, str]], answer: type[BaseModel]) -> AiCall:
        if self._client is None:
            raise AiError("ai_not_configured", "AI_API_KEY is not set")
        started = time.perf_counter()
        try:
            completion = self._client.chat.completions.parse(
                model=self._settings.model,
                messages=cast("list[ChatCompletionMessageParam]", messages),
                response_format=answer,
                reasoning_effort=self._settings.reasoning_effort,
                max_completion_tokens=self._settings.max_output_tokens,
                store=False,
            )
        except (openai.AuthenticationError, openai.PermissionDeniedError) as error:
            raise AiError("ai_not_configured", type(error).__name__) from error
        except (
            openai.APIConnectionError,  # includes timeouts
            openai.RateLimitError,
            openai.InternalServerError,
        ) as error:
            raise AiError("ai_unavailable", type(error).__name__) from error
        except (
            openai.LengthFinishReasonError,  # the answer outgrew AI_MAX_OUTPUT_TOKENS
            openai.ContentFilterFinishReasonError,
            openai.APIStatusError,  # a request the provider refuses: ours to fix
        ) as error:
            raise AiError("detection_failed", type(error).__name__) from error
        latency = time.perf_counter() - started
        choice = completion.choices[0]
        if choice.message.parsed is None:
            raise AiError("detection_failed", choice.message.refusal or str(choice.finish_reason))
        usage = completion.usage
        prompt_details = usage.prompt_tokens_details if usage else None
        output_details = usage.completion_tokens_details if usage else None
        call = AiCall(
            answer=choice.message.parsed.model_dump(mode="json"),
            content=choice.message.content or "",
            request_id=completion.id,
            model=completion.model,
            latency_s=round(latency, 2),
            usage=Usage(
                input=usage.prompt_tokens if usage else 0,
                cached=(prompt_details.cached_tokens or 0) if prompt_details else 0,
                output=usage.completion_tokens if usage else 0,
                reasoning=(output_details.reasoning_tokens or 0) if output_details else 0,
            ),
        )
        log.info(
            "detection.ai_call",
            model=call.model,
            request_id=call.request_id,
            latency_s=call.latency_s,
            input_tokens=call.usage.input,
            output_tokens=call.usage.output,
            reasoning_tokens=call.usage.reasoning,
        )
        return call
