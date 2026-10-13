"""embed_texts(): turn texts into vectors with the configured embedding model, through LiteLLM.

An embedding is a list of numbers that places a text in a "meaning space": texts about the same
thing end up close together, whatever words they use. Policy search (decision 043) embeds every
rule once, embeds a question when someone searches, and asks Postgres (pgvector) for the nearest
rules.

Like complete_structured(), this is the only place that talks to the model for embeddings; it
waits in the same app queue (one local Ollama serves both), checks what comes back, and reports
a failure as an LlmError instead of a provider's exception.
"""

import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import litellm

from app.config import Settings, get_settings
from app.db.models import EMBEDDING_DIM
from app.llm.client import LlmError, call_queue
from app.llm.tracing import trace_metadata

logger = logging.getLogger(__name__)

# litellm.aembedding's shape; tests pass a fake with the same shape.
EmbeddingCall = Callable[..., Awaitable[Any]]
TextKind = Literal["document", "query"]


@dataclass(frozen=True)
class Embedded:
    vectors: list[list[float]]  # one per text, in the same order
    model: str


# What the app passes around, so tests can swap in a fake: texts in, vectors out.
Embedder = Callable[[list[str], TextKind], Awaitable[Embedded]]


async def embed_texts(
    texts: list[str],
    kind: TextKind = "document",
    *,
    settings: Settings | None = None,
    embedding: EmbeddingCall | None = None,
) -> Embedded:
    """One vector of EMBEDDING_DIM numbers per text. `kind` picks the model's task prefix:
    a stored rule is a "document", a search question is a "query"."""
    settings = settings or get_settings()
    embedding = embedding or litellm.aembedding
    prefix = (
        settings.embedding_document_prefix
        if kind == "document"
        else settings.embedding_query_prefix
    )
    started = time.perf_counter()
    async with call_queue(settings.llm_max_concurrency):
        try:
            response = await embedding(
                model=settings.embedding_model,
                api_base=settings.llm_base_url,
                api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
                input=[prefix + text for text in texts],
                timeout=settings.llm_timeout_s,
                metadata=trace_metadata("embeddings", 1),
            )
        except Exception as exc:  # connection refused, timeout, model not pulled, provider error
            logger.warning(
                "embedding call failed",
                extra={
                    "embedding_model": settings.embedding_model,
                    "error_type": type(exc).__name__,
                },
            )
            raise LlmError(
                "unavailable",
                f"The embedding model ({settings.embedding_model}) could not be reached.",
            ) from exc
    vectors = _vectors(response, expected=len(texts), model=settings.embedding_model)
    logger.info(
        "embedding call",
        extra={
            "embedding_model": settings.embedding_model,
            "texts": len(texts),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    return Embedded(vectors, settings.embedding_model)


def _vectors(response: Any, *, expected: int, model: str) -> list[list[float]]:
    """The vectors in the response, checked: the right number, the right width, real numbers."""
    try:
        vectors = [[float(x) for x in item["embedding"]] for item in response.data]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise LlmError("invalid_output", f"The embedding model ({model}) answered oddly.") from exc
    if len(vectors) != expected:
        raise LlmError(
            "invalid_output", f"Asked for {expected} embeddings, got {len(vectors)} ({model})."
        )
    for vector in vectors:
        if len(vector) != EMBEDDING_DIM or not all(math.isfinite(x) for x in vector):
            raise LlmError(
                "invalid_output",
                f"The embedding model ({model}) gave vectors of {len(vector)} numbers; "
                f"this database stores {EMBEDDING_DIM}. Use a {EMBEDDING_DIM}-number model "
                "or add a migration for another width.",
            )
    return vectors
