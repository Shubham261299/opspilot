"""Customers intake: the shop-owner list (customers.xlsx) -> clean customer rows.

parse_customers() is pure: bytes in, result out, no database. A row is loaded only when it
has a party code, a shop name and valid credit terms. A row without a code is never given
one by guessing; if its phone or name matches an existing row it is reported as a likely
duplicate, otherwise as missing its code.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.domain.matching import names_almost_equal
from app.domain.phones import normalise_phone, phone_style
from app.intake.errors import IntakeError
from app.intake.excel import (
    Header,
    SheetRow,
    cells_by_field,
    find_header,
    parse_money,
    raw_cells,
    read_workbook,
)
from app.intake.issues import IssueRecord, IssueType

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "code": ("party code", "customer code", "code", "customer id", "party id"),
    "shop_name": ("shop name", "party name", "customer name", "shop", "party", "name"),
    "contact_person": ("contact person", "contact", "owner", "contact name"),
    "phone": ("mobile", "phone", "mobile no", "phone no", "contact no", "whatsapp"),
    "area": ("area", "location", "locality", "city"),
    "credit_limit": ("credit limit rs", "credit limit", "limit"),
    "credit_days": ("credit days", "credit period", "credit period days", "days"),
}


@dataclass(frozen=True)
class CustomerRow:
    code: str
    shop_name: str
    contact_person: str | None
    phone: str | None  # "+91XXXXXXXXXX"
    area: str | None
    credit_limit: Decimal
    credit_days: int
    source_row: int


@dataclass(frozen=True)
class CustomersResult:
    sheet_name: str
    header_row: int
    rows_read: int
    customers: tuple[CustomerRow, ...]
    issues: tuple[IssueRecord, ...]


def parse_customers(content: bytes) -> CustomersResult:
    for sheet in read_workbook(content):
        header = find_header(
            sheet, HEADER_SYNONYMS, required=("shop_name", "credit_limit"), any_of=("code",)
        )
        if header is not None:
            return _CustomerReader(header).read(sheet.name, sheet.rows)
    raise IntakeError(
        "header_not_found",
        "No header row found. The customers sheet needs 'Party Code', 'Shop Name' and "
        "'Credit Limit' columns.",
    )


class _CustomerReader:
    def __init__(self, header: Header) -> None:
        self.header = header
        self.rows_read = 0
        self.by_code: dict[str, CustomerRow] = {}
        self.issues: list[IssueRecord] = []
        self.phone_styles: dict[str, list[int]] = defaultdict(list)
        self.without_code: list[tuple[SheetRow, dict[str, Any]]] = []

    def read(self, sheet_name: str, rows: tuple[SheetRow, ...]) -> CustomersResult:
        for row in rows:
            if row.number > self.header.row_number and not row.is_blank():
                self.rows_read += 1
                self._read_row(row, cells_by_field(self.header, row))
        # Rows without a code are checked last, against every row that has one.
        for row, cells in self.without_code:
            self._report_missing_code(row, cells)
        self._report_phone_styles()
        customers = sorted(self.by_code.values(), key=lambda c: c.source_row)
        issues = sorted(self.issues, key=lambda i: (i.source_row is None, i.source_row or 0))
        return CustomersResult(
            sheet_name=sheet_name,
            header_row=self.header.row_number,
            rows_read=self.rows_read,
            customers=tuple(customers),
            issues=tuple(issues),
        )

    def _read_row(self, row: SheetRow, cells: dict[str, Any]) -> None:
        code = _text(cells.get("code"))
        if code is None:
            self.without_code.append((row, cells))
            return
        code = code.upper()
        shop_name = _text(cells.get("shop_name"))
        if shop_name is None:
            self._issue(
                IssueType.MISSING_SHOP_NAME,
                f"Party {code} has no shop name, so it was not loaded.",
                row,
                code,
            )
            return
        terms = self._credit_terms(row, cells, code)
        if terms is None:
            return
        phone = self._phone(row, cells, code)
        customer = CustomerRow(
            code=code,
            shop_name=" ".join(shop_name.split()),
            contact_person=_text(cells.get("contact_person")),
            phone=phone,
            area=_text(cells.get("area")),
            credit_limit=terms[0],
            credit_days=terms[1],
            source_row=row.number,
        )
        earlier = self.by_code.get(code)
        if earlier is not None:
            self._issue(
                IssueType.DUPLICATE_ROW,
                f"Party code {code} is listed twice: first on row {earlier.source_row}, again "
                f"here. This later row is kept; row {earlier.source_row} was not loaded.",
                row,
                code,
            )
        self.by_code[code] = customer

    def _credit_terms(
        self, row: SheetRow, cells: dict[str, Any], code: str
    ) -> tuple[Decimal, int] | None:
        limit = parse_money(cells.get("credit_limit")) if cells.get("credit_limit") else None
        days_raw = cells.get("credit_days")
        days = _whole_number(days_raw)
        if limit is None or limit < 0 or days is None or days < 0:
            self._issue(
                IssueType.INVALID_CREDIT_TERMS,
                f"Party {code} has a missing or invalid credit limit "
                f"('{cells.get('credit_limit')}') or credit days ('{days_raw}'), so it was not "
                "loaded: the payment rules can't work without them.",
                row,
                code,
            )
            return None
        return limit, days

    def _phone(self, row: SheetRow, cells: dict[str, Any], code: str) -> str | None:
        raw = cells.get("phone")
        if raw is None:
            return None
        phone = normalise_phone(raw)
        if phone is None:
            self._issue(
                IssueType.INVALID_PHONE,
                f"Mobile '{raw}' is not a valid 10-digit Indian mobile number; "
                f"{code} was loaded without a phone.",
                row,
                code,
            )
            return None
        self.phone_styles[phone_style(raw)].append(row.number)
        return phone

    def _report_missing_code(self, row: SheetRow, cells: dict[str, Any]) -> None:
        name = _text(cells.get("shop_name")) or "(no name)"
        phone = normalise_phone(cells.get("phone"))
        same_phone = [c for c in self.by_code.values() if phone and c.phone == phone]
        similar_name = [c for c in self.by_code.values() if names_almost_equal(name, c.shop_name)]
        match = same_phone or similar_name
        if match:
            twin = match[0]
            why = "same mobile number" if same_phone else "almost the same shop name"
            self._issue(
                IssueType.DUPLICATE_CUSTOMER,
                f"'{name}' has no party code, and has the {why} as {twin.code} "
                f"'{twin.shop_name}', so it looks like a duplicate of {twin.code}. Not loaded; "
                f"if it is a different shop, give it its own party code.",
                row,
                twin.code,
            )
            return
        self._issue(
            IssueType.MISSING_CUSTOMER_CODE,
            f"'{name}' has no party code, so it was not loaded. Give it a code like CUS026.",
            row,
        )

    def _report_phone_styles(self) -> None:
        if len(self.phone_styles) < 2:
            return
        parts = [
            f"{style} (rows {', '.join(map(str, rows))})"
            for style, rows in sorted(self.phone_styles.items())
        ]
        self._issue(
            IssueType.PHONES_NORMALISED,
            f"Mobile numbers were written {len(self.phone_styles)} different ways: "
            f"{'; '.join(parts)}. All are saved as +91 followed by 10 digits.",
            raw={style: rows for style, rows in sorted(self.phone_styles.items())},
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


def _text(value: Any) -> str | None:
    return None if value is None else str(value).strip() or None


def _whole_number(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
