import asyncio
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from app.db.seed import ProductRow, SupplierRow, read_csv_rows
from app.domain.catalog import Catalog, CatalogProduct, CatalogSupplier

# A developer's .env may hold real Langfuse keys. Tests must never send traces, so blank them:
# environment variables win over .env in Settings, and empty keys mean tracing is off.
for _name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
    os.environ[_name] = ""

# backend/tests/conftest.py -> repo root
SAMPLE_DATA_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture(scope="session")
def sample_data_dir() -> Path:
    return SAMPLE_DATA_DIR


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    """The real reference data (6 suppliers, 60 products) from the sample CSVs."""
    suppliers = read_csv_rows(SAMPLE_DATA_DIR / "suppliers.csv", SupplierRow)
    products = read_csv_rows(SAMPLE_DATA_DIR / "product_master.csv", ProductRow)
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


if sys.platform == "win32":
    # psycopg (used by LangGraph's checkpointer) can't run on Windows' default event loop, so
    # tests there use the selector loop. The hook only exists on Windows: pytest-asyncio
    # requires it to return a factory whenever it is defined, and Linux (Docker, CI) needs none.

    def pytest_asyncio_loop_factories(
        config: pytest.Config, item: pytest.Item
    ) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
        return {"selector": asyncio.SelectorEventLoop}
