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
    status: Literal["processing", "processed", "failed"]
    as_of: date | None = Field(
        description="The date the file describes: count date, upload date for dues, last sale"
    )
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


class UploadSummaryOut(BaseModel):
    upload: UploadOut
    issues_by_severity: dict[Severity, int]
    issues_by_type: dict[str, int]


class StockUploadOut(UploadSummaryOut):
    po_notes: list[PoNoteOut]


class CustomersUploadOut(UploadSummaryOut):
    added: list[str] = Field(description="Codes of customers added by this file")
    updated: list[str] = Field(description="Codes of customers whose details changed")


class DuesUploadOut(UploadSummaryOut):
    bills_loaded: int
    total_balance: Decimal


class SalesUploadOut(UploadSummaryOut):
    lines_loaded: int
    last_sale: date | None


class UploadAcceptedOut(BaseModel):
    upload: UploadOut
    message: str


class UploadsOut(BaseModel):
    items: list[UploadOut]


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
    customer_code: str | None
    customer_name: str | None
    raw: dict[str, Any] | None = Field(description="The original cell values")
    resolved: bool


class IssuesOut(BaseModel):
    upload: UploadOut | None
    items: list[IssueOut]


class CustomerOut(BaseModel):
    code: str
    shop_name: str
    contact_person: str | None
    phone: str | None
    area: str | None
    credit_limit: Decimal
    credit_days: int
    on_hold: bool
    hold_reason: str | None
    balance: Decimal = Field(description="Total unpaid in the current dues file")
    open_bills: int
    oldest_bill_date: date | None


class CustomersOut(BaseModel):
    dues_upload_id: int | None = Field(description="The dues upload the balances come from")
    dues_as_of: date | None
    items: list[CustomerOut]


ProposalKind = Literal["reorder", "payment_reminder", "hold_orders", "confirm_order"]
ProposalStatus = Literal["pending", "approved", "rejected", "superseded"]


class ProposalSubjectOut(BaseModel):
    type: Literal["product", "customer", "order"]
    code: str  # SKU, party code, or for an order the party code ("?" if the sender is unknown)
    name: str


class ProposalOut(BaseModel):
    id: int
    kind: ProposalKind
    status: ProposalStatus
    subject: ProposalSubjectOut
    numbers: dict[str, Any] = Field(description="The calculated figures behind the proposal")
    reason: str
    basis: dict[str, Any] = Field(description="What it was calculated from: uploads and today")
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_note: str | None
    purchase_order_id: int | None = Field(description="Created when a reorder is approved")
    payment_reminder_id: int | None = Field(description="Created when a reminder is approved")
    reminder_message: str | None
    order_id: int | None = Field(description="For a confirm_order proposal: the order")
    explanation: str | None = Field(
        description="Written by the language model and checked by code; null until then"
    )
    explained_by: Literal["llm", "template"] | None
    draft_message: str | None = Field(description="A reminder's message for the customer")


class ProposalsOut(BaseModel):
    items: list[ProposalOut]


class RunChecksOut(BaseModel):
    created: int
    unchanged: int
    superseded: int
    already_decided: int = Field(description="Not proposed again: decided before, same numbers")
    pending: int = Field(description="Proposals now waiting for a decision")
    not_checked: list[str] = Field(description="Checks that couldn't run, and why")


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=500, description="Why, in a few words")


class PurchaseOrderLineOut(BaseModel):
    sku: str
    name: str
    qty: int
    unit: str
    unit_cost: Decimal
    amount: Decimal


class PurchaseOrderOut(BaseModel):
    id: int
    status: str
    supplier: SupplierOut
    proposal_id: int
    created_by: str
    created_at: datetime
    lines: list[PurchaseOrderLineOut]
    total: Decimal


class PurchaseOrdersOut(BaseModel):
    items: list[PurchaseOrderOut]


class OrderLineOut(BaseModel):
    id: int
    written: str = Field(description="The product words as the customer wrote them")
    qty: int
    unit_written: str | None
    sku: str | None = Field(description="null: not matched yet; the owner must choose")
    name: str | None
    matched_on: str | None = Field(description="name, alias, same words, model or owner")


class OrderOut(BaseModel):
    id: int
    upload_id: int
    status: Literal["awaiting_confirmation", "confirmed", "rejected"]
    sender: str
    customer_code: str | None
    customer_name: str | None
    first_sent_at: datetime
    source_lines: list[int]
    unclear: list[str]
    lines: list[OrderLineOut]
    proposal_id: int | None


class OrdersOut(BaseModel):
    items: list[OrderOut]


class OrderLineChangeIn(BaseModel):
    sku: str | None = Field(default=None, description="The product this line is, e.g. ST-0021")
    qty: int | None = Field(default=None, gt=0, description="The correct quantity")
    remove: bool = Field(default=False, description="Remove the line instead")


class EnquiryOut(BaseModel):
    id: int
    upload_id: int
    sender: str
    customer_code: str | None
    text: str
    source_line: int
    created_at: datetime


class EnquiriesOut(BaseModel):
    items: list[EnquiryOut]
