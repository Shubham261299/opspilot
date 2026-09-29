"""Seed reference data: suppliers and products from the two sample CSVs.

Run it with:  python -m app.db.seed   (the API container does this on start-up)

It reads ONLY suppliers.csv and product_master.csv. Rows that already exist (same
supplier code or SKU) are left untouched, so running it again is always safe.
"""

import asyncio
import csv
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Product, Supplier
from app.db.session import get_engine, get_sessionmaker
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)

SUPPLIERS_CSV = "suppliers.csv"
PRODUCTS_CSV = "product_master.csv"


class SeedDataError(Exception):
    """The reference data is invalid. It should be clean, so we stop instead of guessing."""


class _CsvRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _blank_cells_to_none(cls, row: dict[str, Any]) -> dict[str, Any]:
        return {key: (value if value not in ("", None) else None) for key, value in row.items()}


class SupplierRow(_CsvRow):
    code: str = Field(alias="id")
    name: str
    phone: str | None = None
    email: str | None = None
    lead_time_days: int = Field(ge=0)
    payment_terms: str | None = None
    categories: str | None = None


class ProductRow(_CsvRow):
    sku: str
    name: str
    aliases: list[str] = []
    unit: str
    pack_size: int = Field(gt=0)
    cost_price: Decimal = Field(ge=0, decimal_places=2)
    sell_price: Decimal = Field(ge=0, decimal_places=2)
    supplier_code: str = Field(alias="supplier_id")

    @field_validator("aliases", mode="before")
    @classmethod
    def _split_aliases(cls, value: str | None) -> list[str]:
        # "6mm wire;6 mm taar;wire 6" -> ["6mm wire", "6 mm taar", "wire 6"]
        return [alias.strip() for alias in (value or "").split(";") if alias.strip()]

    @field_validator("unit")
    @classmethod
    def _lowercase_unit(cls, value: str) -> str:
        return value.lower()


def read_csv_rows[RowT: _CsvRow](path: Path, model: type[RowT]) -> list[RowT]:
    """Parse and validate every row; stop with the file's row number if one is invalid."""
    with path.open(newline="", encoding="utf-8") as file:
        rows = []
        for row_number, raw in enumerate(csv.DictReader(file), start=2):  # row 1 = header
            try:
                rows.append(model.model_validate(raw))
            except ValidationError as exc:
                raise SeedDataError(f"{path.name} row {row_number}: {exc}") from exc
    return rows


@dataclass(frozen=True)
class SeedResult:
    suppliers_added: int
    products_added: int


async def seed_reference_data(
    session: AsyncSession, suppliers: list[SupplierRow], products: list[ProductRow]
) -> SeedResult:
    """Insert suppliers and products that don't exist yet, in one transaction."""
    suppliers_added = products_added = 0

    if suppliers:
        # INSERT ... ON CONFLICT DO NOTHING: existing codes are skipped, not overwritten.
        # RETURNING gives back only the rows that were actually inserted.
        stmt = (
            insert(Supplier)
            .values([supplier.model_dump() for supplier in suppliers])
            .on_conflict_do_nothing(index_elements=[Supplier.code])
            .returning(Supplier.id)
        )
        suppliers_added = len((await session.execute(stmt)).all())

    supplier_ids = dict((await session.execute(select(Supplier.code, Supplier.id))).all())
    unknown = sorted({product.supplier_code for product in products} - supplier_ids.keys())
    if unknown:
        await session.rollback()
        raise SeedDataError(f"{PRODUCTS_CSV} refers to unknown supplier codes: {unknown}")

    if products:
        stmt = (
            insert(Product)
            .values(
                [
                    {
                        **product.model_dump(exclude={"supplier_code"}),
                        "supplier_id": supplier_ids[product.supplier_code],
                    }
                    for product in products
                ]
            )
            .on_conflict_do_nothing(index_elements=[Product.sku])
            .returning(Product.id)
        )
        products_added = len((await session.execute(stmt)).all())

    await session.commit()
    return SeedResult(suppliers_added=suppliers_added, products_added=products_added)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    suppliers = read_csv_rows(settings.seed_data_dir / SUPPLIERS_CSV, SupplierRow)
    products = read_csv_rows(settings.seed_data_dir / PRODUCTS_CSV, ProductRow)
    try:
        async with get_sessionmaker()() as session:
            result = await seed_reference_data(session, suppliers, products)
    finally:
        await get_engine().dispose()
    logger.info(
        "seed complete",
        extra={
            "suppliers_in_file": len(suppliers),
            "suppliers_added": result.suppliers_added,
            "products_in_file": len(products),
            "products_added": result.products_added,
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
