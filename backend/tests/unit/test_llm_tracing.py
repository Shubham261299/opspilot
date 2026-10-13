"""Tracing is optional and can never break a model call."""

import asyncio
import os
from collections.abc import Iterator
from functools import partial
from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from litellm.integrations.custom_logger import CustomLogger
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.llm.client import complete_structured
from app.llm.tracing import flush_tracing, setup_tracing, trace_metadata

URL = "postgresql+asyncpg://unused/unused_test"


def make_settings(**values: Any) -> Settings:
    """Settings from the arguments only: a developer's real .env (with Langfuse keys) is ignored."""
    return Settings(database_url=URL, _env_file=None, **values)


class Answer(BaseModel):
    ok: bool


@pytest.fixture(autouse=True)
def clean_callbacks(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with no callbacks and no Langfuse variables, and leaves none behind."""
    monkeypatch.setattr(litellm, "callbacks", [])
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)
    yield


def test_without_keys_tracing_stays_off() -> None:
    assert setup_tracing(make_settings()) is False
    assert litellm.callbacks == []
    assert "LANGFUSE_PUBLIC_KEY" not in os.environ


def test_empty_keys_count_as_off() -> None:
    """docker-compose passes empty strings when .env has no keys."""
    config = make_settings(langfuse_public_key="", langfuse_secret_key=SecretStr(""))
    assert setup_tracing(config) is False
    assert litellm.callbacks == []


def test_with_keys_the_langfuse_callback_is_added_once() -> None:
    config = make_settings(
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key=SecretStr("sk-lf-test"),
        langfuse_host="https://us.cloud.langfuse.com",
    )
    assert setup_tracing(config) is True
    assert setup_tracing(config) is True  # a second call must not register it twice
    assert litellm.callbacks == ["langfuse_otel"]
    assert os.environ["LANGFUSE_PUBLIC_KEY"] == "pk-lf-test"
    assert os.environ["LANGFUSE_SECRET_KEY"] == "sk-lf-test"
    assert os.environ["LANGFUSE_HOST"] == "https://us.cloud.langfuse.com"


def test_a_broken_setup_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "callbacks", None)  # `in None` fails inside setup_tracing
    config = make_settings(langfuse_public_key="pk", langfuse_secret_key=SecretStr("sk"))
    assert setup_tracing(config) is False


def test_trace_metadata_names_the_call_and_the_attempt() -> None:
    assert trace_metadata("whatsapp_orders", 2) == {
        "generation_name": "whatsapp_orders",
        "trace_name": "whatsapp_orders",
        "tags": ["whatsapp_orders", "attempt-2"],
        "trace_metadata": {"purpose": "whatsapp_orders", "attempt": 2},
    }


class ExplodingCallback(CustomLogger):
    """Stands in for a tracing callback that fails (Langfuse down, bad keys, a bug)."""

    def __init__(self) -> None:
        super().__init__()
        self.was_called = False

    async def async_log_success_event(self, *args: Any, **kwargs: Any) -> None:
        self.was_called = True
        raise RuntimeError("tracing backend is down")


async def test_a_failing_callback_does_not_break_the_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Goes through real litellm.acompletion (with a canned answer, no network)."""
    callback = ExplodingCallback()
    monkeypatch.setattr(litellm, "callbacks", [callback])
    completion = partial(litellm.acompletion, mock_response='{"ok": true}')
    result = await complete_structured(
        [{"role": "user", "content": "hi"}],
        Answer,
        purpose="test",
        settings=make_settings(),
        completion=completion,
    )
    assert result.value == Answer(ok=True)
    assert result.attempts == 1
    for _ in range(50):  # LiteLLM runs callbacks just after the call returns
        if callback.was_called:
            break
        await asyncio.sleep(0.02)
    assert callback.was_called  # the callback really ran and failed


async def test_flushing_with_tracing_off_does_nothing() -> None:
    await flush_tracing(wait_s=0)  # no callback registered: returns without touching LiteLLM


async def test_a_flush_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "callbacks", ["langfuse_otel"])

    class Broken:
        _tracer_provider = SimpleNamespace(force_flush=lambda _ms: 1 / 0)

    from litellm.litellm_core_utils import litellm_logging

    monkeypatch.setattr(litellm_logging, "_in_memory_loggers", [Broken()])
    await flush_tracing(wait_s=0)  # must not raise
