"""Database tables as Python classes (SQLAlchemy 2 typed ORM models).

Each class is one table and each `Mapped[...]` attribute is one column:
`Mapped[str]` is NOT NULL, `Mapped[str | None]` allows NULL. Alembic compares these
classes with the real database to generate migrations, so this file is the single
source of truth for the schema.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names (e.g. "fk_products_supplier_id_suppliers"), so later
# migrations can refer to a constraint by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Default column types for these Python types.
    type_annotation_map = {
        Decimal: Numeric(10, 2),  # money: exact, two decimal places
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[str]: ARRAY(Text),
    }


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (CheckConstraint("lead_time_days >= 0", name="lead_time_not_negative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)  # "SUP01"
    name: Mapped[str] = mapped_column(unique=True)
    phone: Mapped[str | None]
    email: Mapped[str | None]
    lead_time_days: Mapped[int]
    payment_terms: Mapped[str | None]  # "30 days", "Advance"
    categories: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("pack_size > 0", name="pack_size_positive"),
        CheckConstraint("cost_price >= 0 AND sell_price >= 0", name="prices_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(20), unique=True)  # "ST-0051"
    name: Mapped[str]
    aliases: Mapped[list[str]] = mapped_column(server_default="{}")  # how customers write it
    unit: Mapped[str]  # piece, coil, roll, length, packet, box, kg
    pack_size: Mapped[int]
    cost_price: Mapped[Decimal]
    sell_price: Mapped[Decimal]
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Upload(Base):
    """One uploaded file and what happened to it."""

    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint("status IN ('processed', 'failed')", name="status_valid"),
        CheckConstraint(
            "kind IN ('stock_register', 'customers', 'outstanding_dues', 'sales_history')",
            name="kind_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    filename: Mapped[str]
    status: Mapped[str]
    as_of: Mapped[date | None]  # the date the file describes (count date, last sale, …)
    rows_read: Mapped[int] = mapped_column(server_default="0")
    rows_loaded: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None]  # why a failed upload failed
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class StockLevel(Base):
    """One clean stock count: a product's quantity on hand, as of one upload.

    Only valid counts are stored (never negative). A row that can't be trusted
    becomes an Issue instead.
    """

    __tablename__ = "stock_levels"
    __table_args__ = (
        UniqueConstraint("upload_id", "product_id"),
        CheckConstraint("qty_on_hand >= 0", name="qty_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    qty_on_hand: Mapped[int]
    as_of: Mapped[date]
    source_row: Mapped[int]  # row number in the uploaded file
    remarks: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OpenPoNote(Base):
    """A purchase order placed outside the app, found in a stock-register remark,
    e.g. "40 pcs ordered from Brightline on 22/9"."""

    __tablename__ = "open_po_notes"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    qty: Mapped[int]
    ordered_on: Mapped[date | None]
    note: Mapped[str]  # the remark exactly as written
    source_row: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Issue(Base):
    """A data problem found while reading a file. Nothing is dropped silently."""

    __tablename__ = "issues"
    __table_args__ = (
        CheckConstraint("severity IN ('error', 'warning', 'info')", name="severity_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    source_file: Mapped[str]
    source_row: Mapped[int | None]  # None = about the whole file
    issue_type: Mapped[str]  # e.g. "negative_qty", "duplicate_row"
    severity: Mapped[str]  # error = not loaded, warning = loaded but check it, info = FYI
    detail: Mapped[str]
    raw: Mapped[dict[str, Any] | None]  # the original cell values
    resolved: Mapped[bool] = mapped_column(server_default=false())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Customer(Base):
    """A shop that buys from Sharma Traders. Loaded from the customers file; `on_hold` is
    only ever changed by an approved proposal."""

    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint("credit_limit >= 0", name="credit_limit_not_negative"),
        CheckConstraint("credit_days >= 0", name="credit_days_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)  # "CUS001"
    shop_name: Mapped[str]
    contact_person: Mapped[str | None]
    phone: Mapped[str | None]  # normalised: "+919895822412"
    area: Mapped[str | None]
    credit_limit: Mapped[Decimal]
    credit_days: Mapped[int]
    on_hold: Mapped[bool] = mapped_column(server_default=false())
    hold_reason: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SalesLine(Base):
    """One line of the sales history. Each upload is a full export; the latest one is used."""

    __tablename__ = "sales_lines"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), index=True)
    sale_date: Mapped[date]
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    qty: Mapped[int]
    unit_price: Mapped[Decimal]
    amount: Mapped[Decimal]


class CustomerBill(Base):
    """An unpaid (or part-paid) bill from the outstanding dues file, as of one upload."""

    __tablename__ = "customer_bills"
    __table_args__ = (
        UniqueConstraint("upload_id", "bill_no"),
        CheckConstraint("amount >= 0 AND received >= 0", name="amounts_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    bill_no: Mapped[str] = mapped_column(String(20))  # "ST/5402"
    bill_date: Mapped[date]
    amount: Mapped[Decimal]
    received: Mapped[Decimal] = mapped_column(server_default="0")
    balance: Mapped[Decimal]
    source_row: Mapped[int]


class Proposal(Base):
    """An action the system suggests. Nothing happens until a human approves it.

    status: pending -> approved | rejected, or superseded when newer data replaces it.
    """

    __tablename__ = "proposals"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('reorder', 'payment_reminder', 'hold_orders')", name="kind_valid"
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'superseded')", name="status_valid"
        ),
        # A proposal is about exactly one product or exactly one customer.
        CheckConstraint(
            "(product_id IS NULL) <> (customer_id IS NULL)", name="exactly_one_subject"
        ),
        # At most one pending proposal of each kind per product / per customer.
        Index(
            "uq_proposals_pending_product",
            "kind",
            "product_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND product_id IS NOT NULL"),
        ),
        Index(
            "uq_proposals_pending_customer",
            "kind",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND customer_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="pending")
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    numbers: Mapped[dict[str, Any]]  # the calculated figures, e.g. reorder point and qty
    basis: Mapped[dict[str, Any]]  # what it was calculated from: upload ids and "today"
    reason: Mapped[str]  # plain-language explanation shown to the owner
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    decided_at: Mapped[datetime | None]
    decided_by: Mapped[str | None]
    decision_note: Mapped[str | None]


class PurchaseOrder(Base):
    """A purchase order created by approving a reorder proposal (never by the system alone)."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('approved', 'sent', 'received', 'cancelled')", name="status_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), unique=True)
    status: Mapped[str] = mapped_column(server_default="approved")
    created_by: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (CheckConstraint("qty > 0", name="qty_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    qty: Mapped[int]
    unit_cost: Mapped[Decimal]


class PaymentReminder(Base):
    """A reminder created by approving a payment proposal. Sending comes with WhatsApp later."""

    __tablename__ = "payment_reminders"
    __table_args__ = (
        CheckConstraint("status IN ('ready', 'sent', 'cancelled')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), unique=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(server_default="ready")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuditLog(Base):
    """Append-only record of every action that changes data: who, what, when, before, after."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str]
    action: Mapped[str]  # e.g. "upload.stock_register"
    entity_type: Mapped[str]
    entity_id: Mapped[str | None]
    before: Mapped[dict[str, Any] | None]
    after: Mapped[dict[str, Any] | None]
    request_id: Mapped[str | None]  # links the audit row to the request's log lines
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
