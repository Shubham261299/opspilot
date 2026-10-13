"""embed_texts() with a fake embedding call: no network, no model."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.db.models import EMBEDDING_DIM
from app.llm.client import LlmError
from app.llm.embeddings import embed_texts

SETTINGS = Settings(database_url="postgresql+asyncpg://unused/unused_test", _env_file=None)


class FakeEmbedding:
    """Returns one vector per input (the given width), or raises; remembers every call."""

    def __init__(self, width: int = EMBEDDING_DIM, error: Exception | None = None) -> None:
        self.width, self.error = width, error
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        data = [{"embedding": [0.5] * self.width} for _ in kwargs["input"]]
        return SimpleNamespace(data=data)


async def test_each_text_gets_a_vector_and_the_model_is_named() -> None:
    fake = FakeEmbedding()
    result = await embed_texts(["a", "b"], settings=SETTINGS, embedding=fake)
    assert [len(v) for v in result.vectors] == [EMBEDDING_DIM, EMBEDDING_DIM]
    assert result.model == "ollama/nomic-embed-text"
    assert fake.calls[0]["model"] == "ollama/nomic-embed-text"


async def test_documents_and_queries_get_their_own_task_prefix() -> None:
    fake = FakeEmbedding()
    await embed_texts(["rule"], "document", settings=SETTINGS, embedding=fake)
    await embed_texts(["question"], "query", settings=SETTINGS, embedding=fake)
    assert fake.calls[0]["input"] == ["search_document: rule"]
    assert fake.calls[1]["input"] == ["search_query: question"]


async def test_a_call_carries_the_tracing_name() -> None:
    fake = FakeEmbedding()
    await embed_texts(["x"], settings=SETTINGS, embedding=fake)
    assert fake.calls[0]["metadata"]["generation_name"] == "embeddings"


async def test_vectors_of_the_wrong_width_are_refused_with_a_clear_message() -> None:
    with pytest.raises(LlmError) as error:
        await embed_texts(["x"], settings=SETTINGS, embedding=FakeEmbedding(width=384))
    assert error.value.code == "invalid_output"
    assert "384" in error.value.message and str(EMBEDDING_DIM) in error.value.message


async def test_a_wrong_number_of_vectors_is_refused() -> None:
    class Short(FakeEmbedding):
        async def __call__(self, **kwargs: Any) -> Any:
            return SimpleNamespace(data=[{"embedding": [0.0] * EMBEDDING_DIM}])

    with pytest.raises(LlmError) as error:
        await embed_texts(["a", "b"], settings=SETTINGS, embedding=Short())
    assert error.value.code == "invalid_output"


async def test_a_provider_error_becomes_an_unavailable_llm_error() -> None:
    fake = FakeEmbedding(error=ConnectionError("refused"))
    with pytest.raises(LlmError) as error:
        await embed_texts(["x"], settings=SETTINGS, embedding=fake)
    assert error.value.code == "unavailable"
    assert "ollama/nomic-embed-text" in error.value.message
