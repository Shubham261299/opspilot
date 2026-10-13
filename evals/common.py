"""Shared by the eval suites: the sample data, the answer key, and how the model is asked.

The answer key (sample_data/answer_key.json) is read only here and in tests, never by the app
(CLAUDE.md rule 1).
"""

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused/unused")  # no database needed

from app.db.seed import ProductRow, SupplierRow, read_csv_rows  # noqa: E402
from app.domain.catalog import Catalog, CatalogProduct, CatalogSupplier  # noqa: E402
from app.llm.client import Message, complete_structured  # noqa: E402

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


@dataclass(frozen=True)
class Report:
    """What a suite measured. `summary` holds only numbers that don't depend on timing."""

    summary: dict[str, Any]
    details: list[dict[str, Any]]


def as_of(key: dict[str, Any]) -> date:
    return date.fromisoformat(key["as_of"])
