"""Read queries used by the API and the importers. Routers call these; they hold no SQL."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Issue, OpenPoNote, Product, StockLevel, Supplier, Upload
from app.domain.catalog import Catalog, CatalogProduct, CatalogSupplier

STOCK_REGISTER = "stock_register"


@dataclass(frozen=True)
class ReferenceData:
    """The catalog for the pure parsers, plus the database ids to save results with."""

    catalog: Catalog
    product_ids: dict[str, int]  # SKU -> products.id
    supplier_ids: dict[str, int]  # supplier code -> suppliers.id


async def load_reference_data(session: AsyncSession) -> ReferenceData:
    suppliers = (await session.scalars(select(Supplier))).all()
    code_by_id = {supplier.id: supplier.code for supplier in suppliers}
    products = (await session.scalars(select(Product))).all()
    catalog = Catalog.build(
        products=[
            CatalogProduct(
                sku=p.sku,
                name=p.name,
                aliases=tuple(p.aliases),
                unit=p.unit,
                cost_price=p.cost_price,
                sell_price=p.sell_price,
                supplier_code=code_by_id[p.supplier_id],
            )
            for p in products
        ],
        suppliers=[CatalogSupplier(code=s.code, name=s.name) for s in suppliers],
    )
    return ReferenceData(
        catalog=catalog,
        product_ids={p.sku: p.id for p in products},
        supplier_ids={s.code: s.id for s in suppliers},
    )


async def current_stock_upload(session: AsyncSession) -> Upload | None:
    """The stock count that is "current": the processed upload with the latest count date.

    Uploading an older file later doesn't replace a newer count (docs/decisions.md, 010).
    """
    stmt = (
        select(Upload)
        .where(Upload.kind == STOCK_REGISTER, Upload.status == "processed")
        .order_by(Upload.as_of.desc().nulls_last(), Upload.created_at.desc(), Upload.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def get_upload(session: AsyncSession, upload_id: int) -> Upload | None:
    return await session.get(Upload, upload_id)


async def latest_upload(session: AsyncSession) -> Upload | None:
    """The most recently uploaded file, whatever happened to it."""
    stmt = select(Upload).order_by(Upload.created_at.desc(), Upload.id.desc()).limit(1)
    return await session.scalar(stmt)


@dataclass(frozen=True)
class ProductStock:
    product: Product
    supplier: Supplier
    qty_on_hand: int | None  # None = no usable count in the current stock upload
    remarks: str | None
    on_order_qty: int
    open_issue_count: int  # unresolved errors and warnings in the current stock upload


async def products_with_stock(session: AsyncSession, upload_id: int | None) -> list[ProductStock]:
    """Every product with its count, quantity on order and open issues from one stock upload."""
    on_order = (
        select(OpenPoNote.product_id, func.sum(OpenPoNote.qty).label("qty"))
        .where(OpenPoNote.upload_id == upload_id)
        .group_by(OpenPoNote.product_id)
        .subquery()
    )
    open_issues = (
        select(Issue.product_id, func.count().label("count"))
        .where(
            Issue.upload_id == upload_id,
            Issue.severity.in_(("error", "warning")),
            Issue.resolved.is_(False),
        )
        .group_by(Issue.product_id)
        .subquery()
    )
    stmt = (
        select(
            Product,
            Supplier,
            StockLevel.qty_on_hand,
            StockLevel.remarks,
            func.coalesce(on_order.c.qty, 0),
            func.coalesce(open_issues.c.count, 0),
        )
        .join(Supplier, Supplier.id == Product.supplier_id)
        .outerjoin(
            StockLevel, (StockLevel.product_id == Product.id) & (StockLevel.upload_id == upload_id)
        )
        .outerjoin(on_order, on_order.c.product_id == Product.id)
        .outerjoin(open_issues, open_issues.c.product_id == Product.id)
        .order_by(Product.sku)
    )
    rows = (await session.execute(stmt)).all()
    return [
        ProductStock(product, supplier, qty, remarks, int(on_order_qty), int(issue_count))
        for product, supplier, qty, remarks, on_order_qty, issue_count in rows
    ]


@dataclass(frozen=True)
class IssueWithProduct:
    issue: Issue
    sku: str | None
    product_name: str | None


async def issues_for_upload(session: AsyncSession, upload_id: int) -> list[IssueWithProduct]:
    stmt = (
        select(Issue, Product.sku, Product.name)
        .outerjoin(Product, Product.id == Issue.product_id)
        .where(Issue.upload_id == upload_id)
        .order_by(Issue.id)
    )
    rows = (await session.execute(stmt)).all()
    return [IssueWithProduct(issue, sku, name) for issue, sku, name in rows]
