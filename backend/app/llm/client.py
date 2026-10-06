"""complete_structured(): ask the model for JSON in a given shape, and get a validated object.

How a call goes:
1. The messages and the Pydantic schema go to LiteLLM, which turns the schema into the
   provider's "structured output" option (for Ollama, its `format` JSON schema).
2. The answer is parsed and validated with the schema.
3. If it doesn't fit, the model is shown its answer and the validation error, and asked once
   to correct it (the repair retry).
4. If the second answer doesn't fit either, or the model can't be reached, LlmError.

The model is never trusted with arithmetic: callers ask it to extract, classify or word
things, and code checks the result (CLAUDE.md rule 3).
"""

import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings

# LiteLLM downloads a model price list from the internet when imported, unless told to use
# its bundled copy. Keep the app offline-capable and private.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
import litellm  # noqa: E402 - must come after the setting above

logger = logging.getLogger(__name__)

# litellm.acompletion's shape; tests pass a fake with the same shape.
Completion = Callable[..., Awaitable[Any]]
Message = dict[str, str]
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class LlmError(Exception):
    """The model couldn't give a usable answer. Callers decide what to do instead."""

    def __init__(self, code: Literal["unavailable", "invalid_output"], message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LlmResult[T: BaseModel]:
    value: T
    model: str
    attempts: int  # 1, or 2 when the repair retry was needed
    latency_ms: int


async def complete_structured[T: BaseModel](
    messages: list[Message],
    schema: type[T],
    *,
    purpose: str,  # what the call is for, e.g. "whatsapp_orders"; used in logs
    settings: Settings | None = None,
    completion: Completion | None = None,
) -> LlmResult[T]:
    settings = settings or get_settings()
    completion = completion or litellm.acompletion
    started = time.perf_counter()
    conversation = list(messages)
    for attempt in (1, 2):
        raw = await _call(completion, conversation, schema, settings, purpose, attempt)
        try:
            value = schema.model_validate_json(_strip_fences(raw))
        except ValidationError as exc:
            if attempt == 2:
                _log(purpose, settings, attempt, started, ok=False)
                raise LlmError(
                    "invalid_output",
                    f"The model's answer didn't match the expected shape twice ({purpose}).",
                ) from exc
            conversation += [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": "Your answer did not match the required JSON schema:\n"
                    f"{_short(exc)}\nReply again with only the corrected JSON.",
                },
            ]
            continue
        _log(purpose, settings, attempt, started, ok=True)
        return LlmResult(value, settings.llm_model, attempt, _ms_since(started))
    raise AssertionError("unreachable")  # the loop always returns or raises


async def _call(
    completion: Completion,
    messages: list[Message],
    schema: type[BaseModel],
    settings: Settings,
    purpose: str,
    attempt: int,
) -> str:
    try:
        response = await completion(
            model=settings.llm_model,
            api_base=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
            messages=messages,
            response_format=schema,
            temperature=0,  # the same input should give the same answer
            timeout=settings.llm_timeout_s,
        )
    except Exception as exc:  # connection refused, timeout, unknown model, provider error...
        logger.warning(
            "llm call failed",
            extra={"purpose": purpose, "llm_model": settings.llm_model, "attempt": attempt},
        )
        raise LlmError(
            "unavailable", f"The language model ({settings.llm_model}) could not be reached."
        ) from exc
    content = response.choices[0].message.content
    return content if isinstance(content, str) else ""


def _strip_fences(text: str) -> str:
    """Small models sometimes wrap JSON in ```json ... ``` despite being asked not to."""
    match = _FENCE.match(text)
    return match.group(1) if match else text


def _short(error: ValidationError) -> str:
    """The first few validation problems, short enough to send back to the model."""
    return "\n".join(
        f"- {'.'.join(map(str, e['loc'])) or 'answer'}: {e['msg']}" for e in error.errors()[:5]
    )


def _ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _log(purpose: str, settings: Settings, attempts: int, started: float, *, ok: bool) -> None:
    # Sizes and timings only: prompts can contain customers' messages, so they aren't logged.
    logger.info(
        "llm call",
        extra={
            "purpose": purpose,
            "llm_model": settings.llm_model,
            "attempts": attempts,
            "latency_ms": _ms_since(started),
            "ok": ok,
        },
    )
