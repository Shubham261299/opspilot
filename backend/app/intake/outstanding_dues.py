"""Outstanding dues intake: the unpaid-bills sheet (outstanding_dues.xlsx) -> clean bills.

parse_outstanding_dues() is pure. Each bill must belong to a known customer: the party is
matched by its exact code or exact shop name (ignoring case and spaces), never by a guess.
A party that only *almost* matches is reported with the likely customer named, and the bill
is not loaded until a human fixes the name.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.domain.dates import parse_day_first
from app.domain.matching import names_almost_equal, normalise_name
from app.intake.errors import IntakeError
from app.intake.excel import (
    Header,
    SheetRow,
    cells_by_field,
    find_header,
    parse_money,
    raw_cells,
    read_workbook,
    rupees,
)
from app.intake.issues import IssueRecord, IssueType

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "party": ("party", "party name", "customer", "customer name", "shop name", "shop"),
    "bill_no": ("bill no", "bill number", "invoice no", "invoice number", "bill"),
    "bill_date": ("bill date", "invoice date", "date"),
    "amount": ("bill amt", "bill amount", "amount", "invoice amount"),
    "received": ("received", "paid", "amount received", "receipt"),
    "balance": ("balance", "due", "balance due", "outstanding", "pending"),
}


@dataclass(frozen=True)
class BillRow:
    customer_code: str
    bill_no: str
    bill_date: date
    amount: Decimal
    received: Decimal
    balance: Decimal
    source_row: int


@dataclass(frozen=True)
class DuesResult:
    sheet_name: str
    header_row: int
    rows_read: int
    bills: tuple[BillRow, ...]
    issues: tuple[IssueRecord, ...]


def parse_outstanding_dues(content: bytes, customers: Mapping[str, str], today: date) -> DuesResult:
    """`customers` maps party code -> shop name. `today` completes dates written without a year."""
    if not customers:
        raise IntakeError(
            "no_customers", "No customers are loaded yet. Upload the customers file first."
        )
    for sheet in read_workbook(content):
        header = find_header(
            sheet, HEADER_SYNONYMS, required=("party", "bill_no", "amount"), any_of=("bill_date",)
        )
        if header is not None:
            return _DuesReader(header, customers, today).read(sheet.name, sheet.rows)
    raise IntakeError(
        "header_not_found",
        "No header row found. The dues sheet needs 'Party', 'Bill No', 'Bill Date' and "
        "'Bill Amt' columns.",
    )


class _DuesReader:
    def __init__(self, header: Header, customers: Mapping[str, str], today: date) -> None:
        self.header = header
        self.customers = customers
        self.by_name = _unique_names(customers)
        self.today = today
        self.rows_read = 0
        self.bills: dict[str, BillRow] = {}  # bill no -> its latest row
        self.issues: list[IssueRecord] = []
        self.by_name_rows: list[int] = []
        self.text_date_rows: list[int] = []
        self.blank_received_rows: list[int] = []

    def read(self, sheet_name: str, rows: tuple[SheetRow, ...]) -> DuesResult:
        for row in rows:
            if row.number > self.header.row_number and not row.is_blank():
                self.rows_read += 1
                self._read_row(row, cells_by_field(self.header, row))
        self._report_file_patterns()
        bills = sorted(self.bills.values(), key=lambda bill: bill.source_row)
        issues = sorted(self.issues, key=lambda i: (i.source_row is None, i.source_row or 0))
        return DuesResult(
            sheet_name=sheet_name,
            header_row=self.header.row_number,
            rows_read=self.rows_read,
            bills=tuple(bills),
            issues=tuple(issues),
        )

    def _read_row(self, row: SheetRow, cells: dict[str, Any]) -> None:
        party = self._customer(row, cells)
        if party is None:
            return
        code, by_name = party
        bill_no = _text(cells.get("bill_no"))
        bill_date, date_as_text = self._bill_date(cells.get("bill_date"))
        amount = parse_money(cells["amount"]) if cells.get("amount") is not None else None
        raw_received = cells.get("received")
        received = self._received(raw_received)
        if bill_no is None or bill_date is None or amount is None or amount < 0 or received is None:
            self._issue(
                IssueType.INVALID_BILL,
                "The bill number, bill date, bill amount or received amount is missing or not "
                "readable, so this bill was not loaded.",
                row,
                code,
            )
            return
        balance = amount - received
        written = parse_money(cells["balance"]) if cells.get("balance") is not None else None
        if written is not None and written != balance:
            self._issue(
                IssueType.BALANCE_MISMATCH,
                f"Balance is written as {rupees(written)}, but bill amount {rupees(amount)} minus "
                f"received {rupees(received)} is {rupees(balance)}. The calculated balance is "
                "used.",
                row,
                code,
            )
        if balance <= 0:
            self._issue(
                IssueType.PAID_BILL,
                f"Bill {bill_no} is fully paid (balance {rupees(balance)}), so it is not counted "
                "as outstanding.",
                row,
                code,
            )
            return
        if bill_date > self.today:
            self._issue(
                IssueType.FUTURE_BILL_DATE,
                f"Bill date {bill_date:%d %b %Y} is after today; check it. The bill was loaded.",
                row,
                code,
            )
        earlier = self.bills.get(bill_no)
        if earlier is not None:
            self._issue(
                IssueType.DUPLICATE_ROW,
                f"Bill {bill_no} is listed twice: first on row {earlier.source_row}, again here. "
                f"This later row is kept; row {earlier.source_row} was not loaded.",
                row,
                code,
            )
        self.bills[bill_no] = BillRow(
            code, bill_no, bill_date, amount, received, balance, row.number
        )
        # Corrections reported once for the whole file, counting only bills that loaded.
        for happened, rows in (
            (by_name, self.by_name_rows),
            (date_as_text, self.text_date_rows),
            (raw_received is None, self.blank_received_rows),
        ):
            if happened:
                rows.append(row.number)

    def _customer(self, row: SheetRow, cells: dict[str, Any]) -> tuple[str, bool] | None:
        """(customer code, whether it was found by shop name), or None with an issue."""
        party = _text(cells.get("party"))
        if party is None:
            self._issue(
                IssueType.UNKNOWN_CUSTOMER, "The party is blank, so this bill was not loaded.", row
            )
            return None
        if party.upper() in self.customers:
            return party.upper(), False
        code = self.by_name.get(normalise_name(party))
        if code is not None:
            return code, True
        close = [c for c, name in self.customers.items() if names_almost_equal(party, name)]
        hint = (
            f" It is close to {close[0]} '{self.customers[close[0]]}'; if that is the same "
            "shop, correct the name in the sheet."
            if len(close) == 1
            else ""
        )
        self._issue(
            IssueType.UNKNOWN_CUSTOMER,
            f"Party '{party}' matches no customer code or shop name, so this bill was not "
            f"loaded.{hint}",
            row,
            close[0] if len(close) == 1 else None,
        )
        return None

    def _bill_date(self, value: Any) -> tuple[date | None, bool]:
        """(the date, whether it was typed as text)."""
        if isinstance(value, datetime):
            return value.date(), False
        if isinstance(value, date):
            return value, False
        if isinstance(value, str):
            return parse_day_first(value, self.today), True
        return None, False

    def _received(self, value: Any) -> Decimal | None:
        if value is None:
            return Decimal(0)
        received = parse_money(value)
        return received if received is not None and received >= 0 else None

    def _report_file_patterns(self) -> None:
        """Corrections made on many rows are reported once for the file, with the rows."""
        if self.by_name_rows:
            self._issue(
                IssueType.PARTY_BY_NAME,
                f"Parties are written by shop name instead of party code on "
                f"{len(self.by_name_rows)} rows; each one matched exactly one customer by name.",
                raw={"rows": self.by_name_rows},
            )
        if self.text_date_rows:
            self._issue(
                IssueType.DATES_AS_TEXT,
                f"Bill dates on {len(self.text_date_rows)} rows are typed as text "
                f"(rows {', '.join(map(str, self.text_date_rows))}); they were read day first, "
                "like 15-08-2026 = 15 Aug 2026.",
                raw={"rows": self.text_date_rows},
            )
        if self.blank_received_rows:
            self._issue(
                IssueType.BLANK_RECEIVED,
                f"'Received' is blank on {len(self.blank_received_rows)} rows; read as nothing "
                "received yet (₹0).",
                raw={"rows": self.blank_received_rows},
            )

    def _issue(
        self,
        issue_type: IssueType,
        detail: str,
        row: SheetRow | None = None,
        customer_code: str | None = None,
        raw: dict[str, Any] | None = None,
    ) -> None:
        if raw is None and row is not None:
            raw = raw_cells(self.header, row)
        source_row = row.number if row is not None else None
        self.issues.append(
            IssueRecord(issue_type, detail, source_row, raw=raw, customer_code=customer_code)
        )


def _unique_names(customers: Mapping[str, str]) -> dict[str, str]:
    """Normalised shop name -> code, leaving out names shared by two customers (ambiguous)."""
    seen: dict[str, list[str]] = {}
    for code, name in customers.items():
        seen.setdefault(normalise_name(name), []).append(code)
    return {name: codes[0] for name, codes in seen.items() if len(codes) == 1}


def _text(value: Any) -> str | None:
    return None if value is None else str(value).strip() or None
