"""The JSON shapes the API returns. FastAPI checks every response against these models.

Money is sent as a string ("1150.00"): JavaScript numbers are floats, and floats can't
hold every rupee-and-paise amount exactly (docs/decisions.md, 019).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["error", "warning", "info"]


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # can be built straight from the ORM row

    id: int
    kind: str
    filename: str
    status: Literal["processed", "failed"]
    as_of: date | None = Field(description="Count date read from the file")
    rows_read: int
    rows_loaded: int
    error: str | None
    created_at: datetime


class PoNoteOut(BaseModel):
    sku: str
    supplier_code: str | None
    qty: int
    ordered_on: date | None
    note: str
    source_row: int


class StockUploadOut(BaseModel):
    upload: UploadOut
    issues_by_severity: dict[Severity, int]
    issues_by_type: dict[str, int]
    po_notes: list[PoNoteOut]


class SupplierOut(BaseModel):
    code: str
    name: str


class ProductOut(BaseModel):
    sku: str
    name: str
    aliases: list[str]
    unit: str
    pack_size: int
    cost_price: Decimal
    sell_price: Decimal
    supplier: SupplierOut
    qty_on_hand: int | None = Field(
        description="From the current stock count; null when that count had no usable number"
    )
    on_order_qty: int = Field(description="Open purchase orders noted in the current stock count")
    remarks: str | None
    open_issue_count: int = Field(description="Unresolved errors and warnings for this product")


class ProductsOut(BaseModel):
    stock_upload_id: int | None = Field(description="The upload the stock numbers come from")
    as_of: date | None = Field(description="Count date of that upload")
    items: list[ProductOut]


class IssueOut(BaseModel):
    id: int
    source_file: str
    source_row: int | None = Field(description="Row number in the file; null = whole file")
    issue_type: str
    severity: Severity
    detail: str
    sku: str | None
    product_name: str | None
    raw: dict[str, Any] | None = Field(description="The original cell values")
    resolved: bool


class IssuesOut(BaseModel):
    upload: UploadOut | None
    items: list[IssueOut]
