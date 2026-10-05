"""Sales history intake: the 90-day sales export (CSV) -> clean sales lines.

parse_sales_history() is pure. The file comes from the billing software, so it is usually
clean, but every row is still checked: a line with an unknown customer or product, or a
quantity or date that can't be read, is not loaded and becomes an issue.
"""

import csv
import io
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.intake.errors import IntakeError
from app.intake.excel import normalise_label, parse_money, rupees
from app.intake.issues import IssueRecord, IssueType

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("date", "sale date", "bill date", "invoice date"),
    "customer": ("customer id", "customer", "customer code", "party code", "party"),
    "sku": ("sku", "item code", "product code", "code"),
    "qty": ("qty", "quantity"),
    "unit_price": ("unit price", "rate", "price"),
    "amount": ("amount", "value", "total"),
}
REQUIRED = ("date", "customer", "sku", "qty")


@dataclass(frozen=True)
class SaleRow:
    sale_date: date
    customer_code: str
    sku: str
    qty: int
    unit_price: Decimal
    amount: Decimal
    source_row: int  # line number in the file; the header is line 1


@dataclass(frozen=True)
class SalesResult:
    rows_read: int
    sales: tuple[SaleRow, ...]
    issues: tuple[IssueRecord, ...]

    @property
    def last_sale(self) -> date | None:
        return max((sale.sale_date for sale in self.sales), default=None)


def parse_sales_history(
    content: bytes, customer_codes: Collection[str], skus: Collection[str]
) -> SalesResult:
    if not customer_codes:
        raise IntakeError(
            "no_customers", "No customers are loaded yet. Upload the customers file first."
        )
    try:
        text = content.decode("utf-8-sig")  # -sig: ignore the byte-order mark Excel adds
    except UnicodeDecodeError as exc:
        raise IntakeError("unreadable_file", "The file is not a UTF-8 CSV file.") from exc
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    columns = _columns(header or [])
    if not all(field in columns for field in REQUIRED):
        raise IntakeError(
            "header_not_found",
            "The first line must be a header with date, customer, SKU and qty columns.",
        )

    sales: list[SaleRow] = []
    issues: list[IssueRecord] = []
    rows_read = 0
    for line_number, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue
        rows_read += 1
        values = {
            field: cells[col].strip() if col < len(cells) else "" for field, col in columns.items()
        }
        raw: dict[str, Any] = {(header or [])[col]: values[field] for field, col in columns.items()}
        sale, issue = _read_sale(values, line_number, raw, customer_codes, skus)
        if issue is not None:
            issues.append(issue)
        if sale is not None:
            sales.append(sale)
    return SalesResult(rows_read=rows_read, sales=tuple(sales), issues=tuple(issues))


def _read_sale(
    values: dict[str, str],
    line: int,
    raw: dict[str, Any],
    customer_codes: Collection[str],
    skus: Collection[str],
) -> tuple[SaleRow | None, IssueRecord | None]:
    customer = values["customer"].upper()
    sku = values["sku"].upper()
    if customer not in customer_codes:
        return None, IssueRecord(
            IssueType.UNKNOWN_CUSTOMER,
            f"Customer '{values['customer']}' is not a known party code, so this sale was not "
            "loaded.",
            line,
            raw=raw,
        )
    if sku not in skus:
        return None, IssueRecord(
            IssueType.UNKNOWN_ITEM,
            f"SKU '{values['sku']}' is not in the product master, so this sale was not loaded.",
            line,
            raw=raw,
            customer_code=customer,
        )
    try:
        sale_date = date.fromisoformat(values["date"])
        qty = int(values["qty"])
    except ValueError:
        sale_date, qty = None, 0
    price = parse_money(values.get("unit_price") or "0")
    if sale_date is None or qty <= 0 or price is None or price < 0:
        return None, IssueRecord(
            IssueType.INVALID_SALE,
            "The date (YYYY-MM-DD), quantity (a whole number above 0) or unit price can't be "
            "read, so this sale was not loaded.",
            line,
            sku,
            raw=raw,
            customer_code=customer,
        )
    amount = qty * price
    issue = None
    written = parse_money(values["amount"]) if values.get("amount") else None
    if written is not None and written != amount:
        issue = IssueRecord(
            IssueType.AMOUNT_MISMATCH,
            f"Amount is {rupees(written)}, but {qty} × {rupees(price)} is {rupees(amount)}; "
            "the calculated amount is used.",
            line,
            sku,
            raw=raw,
            customer_code=customer,
        )
    return SaleRow(sale_date, customer, sku, qty, price, amount, line), issue


def _columns(header: list[str]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for col, title in enumerate(header):
        label = normalise_label(title)
        for field, names in HEADER_SYNONYMS.items():
            if field not in columns and label in names:
                columns[field] = col
                break
    return columns
