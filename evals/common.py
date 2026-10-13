"""Shared by the eval suites: the sample data, the answer key, and how the model is asked.

The answer key (sample_data/answer_key.json) is read only here and in tests, never by the app
(CLAUDE.md rule 1).
"""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused/unused")  # no database needed

from app.db.seed import ProductRow, SupplierRow, read_csv_rows  # noqa: E402
from app.domain.catalog import Catalog, CatalogProduct, CatalogSupplier  # noqa: E402
from app.llm.client import Message, complete_structured  # noqa: E402
from app.llm.embeddings import Embedded, TextKind, embed_texts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "sample_data"
RECORDINGS = ROOT / "evals" / "recordings"
RESULTS = ROOT / "evals" / "results"

Completion = Callable[..., Awaitable[Any]]


def load_answer_key() -> dict[str, Any]:
    return json.loads((DATA / "answer_key.json").read_text(encoding="utf-8"))


def load_catalog() -> Catalog:
    suppliers = read_csv_rows(DATA / "suppliers.csv", SupplierRow)
    products = read_csv_rows(DATA / "product_master.csv", ProductRow)
    return Catalog.build(
        products=[
            CatalogProduct(
                sku=p.sku,
                name=p.name,
                aliases=tuple(p.aliases),
                unit=p.unit,
                cost_price=p.cost_price,
                sell_price=p.sell_price,
                supplier_code=p.supplier_code,
            )
            for p in products
        ],
        suppliers=[CatalogSupplier(code=s.code, name=s.name) for s in suppliers],
    )


@dataclass
class CountingAsk:
    """The app's `Ask`: complete_structured through the given completion, counting the calls.

    `completion` is litellm.acompletion's shape: the real model, a recorder around it, or a
    tape replay (see tape.py).
    """

    completion: Completion
    calls: int = field(default=0)

    async def __call__[T: BaseModel](
        self, messages: list[Message], schema: type[T], purpose: str
    ) -> T:
        self.calls += 1
        result = await complete_structured(
            messages, schema, purpose=purpose, completion=self.completion
        )
        return result.value


@dataclass
class CountingEmbedding:
    """litellm.aembedding's shape, counting calls (the real model, a recorder or a replay)."""

    call: Completion
    calls: int = 0

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls += 1
        return await self.call(**kwargs)


@dataclass
class Models:
    """The language models an eval suite may use: chat answers and embeddings. Each is a
    litellm-shaped call: the real model, a tape recorder around it, or a tape replay."""

    chat: Completion
    embedding: Completion

    def __post_init__(self) -> None:
        self.ask = CountingAsk(self.chat)
        self.counted_embedding = CountingEmbedding(self.embedding)

    async def embed(self, texts: list[str], kind: TextKind = "document") -> Embedded:
        """The app's `Embedder`, over this models' embedding call."""
        return await embed_texts(texts, kind, embedding=self.counted_embedding)


def eval_database_url() -> str:
    """The Postgres the policy eval uses: the same one the integration tests use, and as for
    them, its name must end in _test because the eval empties it first."""
    url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+asyncpg://opspilot:opspilot@localhost:5433/opspilot_test"
    )
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        raise SystemExit(f"Refusing to use database {database!r}: its name must end in _test.")
    return url


async def prepare_database(url: str) -> None:
    """An empty, fully migrated database. Needs pgvector Postgres: `docker compose up -d db`."""
    parsed = make_url(url)
    admin = create_async_engine(
        parsed.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": parsed.database}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    await admin.dispose()
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    # Alembic starts its own event loop, so it can't run inside this one.
    await asyncio.to_thread(command.upgrade, config, "head")


@dataclass(frozen=True)
class Report:
    """What a suite measured. `summary` holds only numbers that don't depend on timing."""

    summary: dict[str, Any]
    details: list[dict[str, Any]]


def as_of(key: dict[str, Any]) -> date:
    return date.fromisoformat(key["as_of"])
