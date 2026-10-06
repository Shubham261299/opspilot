"""complete_structured() with a fake model: no network, the same answers every run."""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.config import Settings
from app.llm.client import LlmError, complete_structured

SETTINGS = Settings(database_url="postgresql+asyncpg://unused/unused_test")


class Line(BaseModel):
    product_text: str
    qty: int


class Lines(BaseModel):
    lines: list[Line]


class FakeModel:
    """Answers with the given texts in turn (or raises), and remembers every call."""

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])


ASK = [{"role": "user", "content": "10 pkt gitti"}]
GOOD = '{"lines": [{"product_text": "gitti", "qty": 10}]}'


async def ask(model: FakeModel) -> Any:
    return await complete_structured(
        ASK, Lines, purpose="test", settings=SETTINGS, completion=model
    )


async def test_a_valid_answer_is_returned_as_the_schema() -> None:
    model = FakeModel(GOOD)
    result = await ask(model)
    assert result.value == Lines(lines=[Line(product_text="gitti", qty=10)])
    assert (result.attempts, result.model) == (1, "ollama_chat/qwen2.5:7b")
    call = model.calls[0]
    assert (call["response_format"], call["temperature"], call["messages"]) == (Lines, 0, ASK)


async def test_json_wrapped_in_a_code_fence_is_accepted() -> None:
    result = await ask(FakeModel(f"```json\n{GOOD}\n```"))
    assert result.value.lines[0].qty == 10


async def test_a_wrong_answer_gets_one_repair_retry_that_shows_the_problem() -> None:
    model = FakeModel('{"lines": [{"product_text": "gitti", "qty": "ten"}]}', GOOD)
    result = await ask(model)
    assert result.attempts == 2
    retry = model.calls[1]["messages"]
    assert retry[1]["role"] == "assistant"  # its own wrong answer...
    assert "lines.0.qty" in retry[2]["content"]  # ...and exactly what was wrong with it


async def test_two_wrong_answers_raise_invalid_output() -> None:
    model = FakeModel("not json", "still not json")
    with pytest.raises(LlmError) as error:
        await ask(model)
    assert error.value.code == "invalid_output"
    assert len(model.calls) == 2  # one repair retry, no more


async def test_an_unreachable_model_raises_unavailable_without_retrying() -> None:
    model = FakeModel(ConnectionError("refused"))
    with pytest.raises(LlmError) as error:
        await ask(model)
    assert error.value.code == "unavailable"
    assert len(model.calls) == 1


async def test_an_api_key_is_passed_only_when_configured() -> None:
    model = FakeModel(GOOD, GOOD)
    await ask(model)
    hosted = SETTINGS.model_copy(update={"llm_api_key": SecretStr("secret")})
    await complete_structured(ASK, Lines, purpose="test", settings=hosted, completion=model)
    assert [call["api_key"] for call in model.calls] == [None, "secret"]
