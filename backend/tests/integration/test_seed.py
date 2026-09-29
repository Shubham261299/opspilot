from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Product, Supplier
from app.db.seed import ProductRow, SupplierRow, read_csv_rows, seed_reference_data


def _reference_rows(sample_data_dir: Path) -> tuple[list[SupplierRow], list[ProductRow]]:
    return (
        read_csv_rows(sample_data_dir / "suppliers.csv", SupplierRow),
        read_csv_rows(sample_data_dir / "product_master.csv", ProductRow),
    )


async def test_seed_adds_reference_data_once(
    db_session: AsyncSession, sample_data_dir: Path
) -> None:
    suppliers, products = _reference_rows(sample_data_dir)

    first = await seed_reference_data(db_session, suppliers, products)
    second = await seed_reference_data(db_session, suppliers, products)

    assert (first.suppliers_added, first.products_added) == (6, 60)
    assert (second.suppliers_added, second.products_added) == (0, 0)
    assert await db_session.scalar(select(func.count()).select_from(Supplier)) == 6
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 60


async def test_seeded_product_keeps_aliases_price_and_supplier(
    db_session: AsyncSession, sample_data_dir: Path
) -> None:
    await seed_reference_data(db_session, *_reference_rows(sample_data_dir))

    product, supplier_code = (
        await db_session.execute(
            select(Product, Supplier.code).join(Supplier).where(Product.sku == "ST-0051")
        )
    ).one()

    assert product.aliases == ["gitti", "wall plug", "rawl plug"]
    assert product.cost_price == Decimal("35.00")
    assert supplier_code == "SUP06"


async def test_seed_never_overwrites_existing_rows(
    db_session: AsyncSession, sample_data_dir: Path
) -> None:
    suppliers, products = _reference_rows(sample_data_dir)
    await seed_reference_data(db_session, suppliers, products)
    product = await db_session.scalar(select(Product).where(Product.sku == "ST-0001"))
    assert product is not None
    product.sell_price = Decimal("1499.00")  # a later change made in the app
    await db_session.commit()

    await seed_reference_data(db_session, suppliers, products)

    await db_session.refresh(product)
    assert product.sell_price == Decimal("1499.00")
