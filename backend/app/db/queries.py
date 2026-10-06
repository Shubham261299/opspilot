"""Read queries used by the API and the importers. Routers call these; they hold no SQL."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Customer,
    CustomerBill,
    CustomerOrder,
    CustomerOrderLine,
    Enquiry,
    Issue,
    OpenPoNote,
    PaymentReminder,
    Product,
    Proposal,
    PurchaseOrder,
    PurchaseOrderLine,
    StockLevel,
    Supplier,
    Upload,
)
from app.domain.catalog import Catalog, CatalogProduct, CatalogSupplier

# Upload kinds (uploads.kind)
STOCK_REGISTER = "stock_register"
CUSTOMERS = "customers"
OUTSTANDING_DUES = "outstanding_dues"
SALES_HISTORY = "sales_history"
WHATSAPP_CHAT = "whatsapp_chat"


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


async def current_upload(session: AsyncSession, kind: str) -> Upload | None:
    """The "current" file of one kind: the processed upload with the latest as-of date.

    Uploading an older file later doesn't replace a newer one (docs/decisions.md, 010).
    """
    stmt = (
        select(Upload)
        .where(Upload.kind == kind, Upload.status == "processed")
        .order_by(Upload.as_of.desc().nulls_last(), Upload.created_at.desc(), Upload.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def current_stock_upload(session: AsyncSession) -> Upload | None:
    return await current_upload(session, STOCK_REGISTER)


async def all_customers(session: AsyncSession) -> list[Customer]:
    return list((await session.scalars(select(Customer).order_by(Customer.code))).all())


@dataclass(frozen=True)
class CustomerDues:
    customer: Customer
    balance: Decimal  # total unpaid in the current dues file
    open_bills: int
    oldest_bill_date: date | None


async def customers_with_dues(
    session: AsyncSession, dues_upload_id: int | None
) -> list[CustomerDues]:
    """Every customer with the total of their unpaid bills in one dues upload."""
    bills = (
        select(
            CustomerBill.customer_id,
            func.sum(CustomerBill.balance).label("balance"),
            func.count().label("open_bills"),
            func.min(CustomerBill.bill_date).label("oldest"),
        )
        .where(CustomerBill.upload_id == dues_upload_id)
        .group_by(CustomerBill.customer_id)
        .subquery()
    )
    stmt = (
        select(Customer, bills.c.balance, bills.c.open_bills, bills.c.oldest)
        .outerjoin(bills, bills.c.customer_id == Customer.id)
        .order_by(Customer.code)
    )
    rows = (await session.execute(stmt)).all()
    return [
        CustomerDues(customer, balance or Decimal(0), open_bills or 0, oldest)
        for customer, balance, open_bills, oldest in rows
    ]


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
    # On order = PO notes in the stock sheet + purchase orders approved in OpsPilot.
    noted = select(OpenPoNote.product_id, OpenPoNote.qty).where(OpenPoNote.upload_id == upload_id)
    approved = (
        select(PurchaseOrderLine.product_id, PurchaseOrderLine.qty)
        .join(PurchaseOrder)
        .where(PurchaseOrder.status.in_(("approved", "sent")))
    )
    both = noted.union_all(approved).subquery()
    on_order = (
        select(both.c.product_id, func.sum(both.c.qty).label("qty"))
        .group_by(both.c.product_id)
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
class IssueWithSubject:
    issue: Issue
    sku: str | None
    product_name: str | None
    customer_code: str | None
    customer_name: str | None


async def issues_for_upload(session: AsyncSession, upload_id: int) -> list[IssueWithSubject]:
    stmt = (
        select(Issue, Product.sku, Product.name, Customer.code, Customer.shop_name)
        .outerjoin(Product, Product.id == Issue.product_id)
        .outerjoin(Customer, Customer.id == Issue.customer_id)
        .where(Issue.upload_id == upload_id)
        .order_by(Issue.id)
    )
    rows = (await session.execute(stmt)).all()
    return [IssueWithSubject(*row) for row in rows]


async def recent_uploads(session: AsyncSession, limit: int = 50) -> list[Upload]:
    stmt = select(Upload).order_by(Upload.created_at.desc(), Upload.id.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


@dataclass(frozen=True)
class ProposalView:
    proposal: Proposal
    sku: str | None
    product_name: str | None
    customer_code: str | None
    customer_name: str | None
    purchase_order_id: int | None
    payment_reminder_id: int | None
    reminder_message: str | None
    order_sender: str | None


def _proposal_views() -> Select[Any]:
    """A proposal with its product or customer and what approving it created."""
    return (
        select(
            Proposal,
            Product.sku,
            Product.name,
            Customer.code,
            Customer.shop_name,
            PurchaseOrder.id,
            PaymentReminder.id,
            PaymentReminder.message,
            CustomerOrder.sender,
        )
        .outerjoin(Product, Product.id == Proposal.product_id)
        .outerjoin(CustomerOrder, CustomerOrder.id == Proposal.order_id)
        # the customer: the proposal's own, or the order's
        .outerjoin(
            Customer,
            Customer.id == func.coalesce(Proposal.customer_id, CustomerOrder.customer_id),
        )
        .outerjoin(PurchaseOrder, PurchaseOrder.proposal_id == Proposal.id)
        .outerjoin(PaymentReminder, PaymentReminder.proposal_id == Proposal.id)
    )


async def list_proposals(session: AsyncSession, status: str) -> list[ProposalView]:
    """Proposals with one status. Pending: oldest first (a queue); decided: newest first."""
    order = (
        (Proposal.kind, Proposal.id)
        if status == "pending"
        else (Proposal.decided_at.desc().nulls_last(), Proposal.id.desc())
    )
    stmt = _proposal_views().where(Proposal.status == status).order_by(*order).limit(500)
    return [ProposalView(*row) for row in (await session.execute(stmt)).all()]


async def get_proposal_view(session: AsyncSession, proposal_id: int) -> ProposalView | None:
    row = (await session.execute(_proposal_views().where(Proposal.id == proposal_id))).first()
    return ProposalView(*row) if row is not None else None


@dataclass(frozen=True)
class PurchaseOrderView:
    order: PurchaseOrder
    supplier: Supplier
    lines: list[tuple[PurchaseOrderLine, Product]]


async def list_purchase_orders(session: AsyncSession) -> list[PurchaseOrderView]:
    orders = (
        await session.execute(
            select(PurchaseOrder, Supplier)
            .join(Supplier)
            .order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
            .limit(200)
        )
    ).all()
    lines = (
        await session.execute(
            select(PurchaseOrderLine, Product)
            .join(Product)
            .where(PurchaseOrderLine.purchase_order_id.in_([o.id for o, _ in orders]))
            .order_by(PurchaseOrderLine.id)
        )
    ).all()
    by_order: dict[int, list[tuple[PurchaseOrderLine, Product]]] = {}
    for line, product in lines:
        by_order.setdefault(line.purchase_order_id, []).append((line, product))
    return [PurchaseOrderView(o, sup, by_order.get(o.id, [])) for o, sup in orders]


@dataclass(frozen=True)
class OrderView:
    order: CustomerOrder
    customer: Customer | None
    lines: list[tuple[CustomerOrderLine, Product | None]]
    proposal_id: int | None


async def list_orders(
    session: AsyncSession, status: str | None = None, order_id: int | None = None
) -> list[OrderView]:
    stmt = (
        select(CustomerOrder, Customer)
        .outerjoin(Customer, Customer.id == CustomerOrder.customer_id)
        .order_by(CustomerOrder.first_sent_at.desc(), CustomerOrder.id.desc())
        .limit(500)
    )
    if status is not None:
        stmt = stmt.where(CustomerOrder.status == status)
    if order_id is not None:
        stmt = stmt.where(CustomerOrder.id == order_id)
    orders = (await session.execute(stmt)).all()
    ids = [order.id for order, _ in orders]
    lines = (
        await session.execute(
            select(CustomerOrderLine, Product)
            .outerjoin(Product, Product.id == CustomerOrderLine.product_id)
            .where(CustomerOrderLine.order_id.in_(ids))
            .order_by(CustomerOrderLine.id)
        )
    ).all()
    proposals = dict(
        (
            await session.execute(
                select(Proposal.order_id, func.max(Proposal.id))
                .where(Proposal.order_id.in_(ids))
                .group_by(Proposal.order_id)
            )
        ).all()
    )
    by_order: dict[int, list[tuple[CustomerOrderLine, Product | None]]] = {}
    for line, product in lines:
        by_order.setdefault(line.order_id, []).append((line, product))
    return [
        OrderView(order, customer, by_order.get(order.id, []), proposals.get(order.id))
        for order, customer in orders
    ]


async def list_enquiries(session: AsyncSession) -> list[tuple[Enquiry, str | None]]:
    rows = await session.execute(
        select(Enquiry, Customer.code)
        .outerjoin(Customer, Customer.id == Enquiry.customer_id)
        .order_by(Enquiry.id.desc())
        .limit(500)
    )
    return [(enquiry, code) for enquiry, code in rows.all()]
