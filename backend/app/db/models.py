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
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
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
    __table_args__ = (CheckConstraint("status IN ('processed', 'failed')", name="status_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]  # "stock_register" for now
    filename: Mapped[str]
    status: Mapped[str]
    as_of: Mapped[date | None]  # the count date found inside the file
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
    source_file: Mapped[str]
    source_row: Mapped[int | None]  # None = about the whole file
    issue_type: Mapped[str]  # e.g. "negative_qty", "duplicate_row"
    severity: Mapped[str]  # error = not loaded, warning = loaded but check it, info = FYI
    detail: Mapped[str]
    raw: Mapped[dict[str, Any] | None]  # the original cell values
    resolved: Mapped[bool] = mapped_column(server_default=false())
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
