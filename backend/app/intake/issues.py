"""Issues: every data problem found while reading a file.

Each issue type always has the same severity:
- error:   the row (or its quantity) was NOT loaded
- warning: loaded, but a human should check it
- info:    handled automatically; listed so nothing changes silently
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]


class IssueType(StrEnum):
    # error
    UNKNOWN_ITEM = "unknown_item"
    CODE_NAME_MISMATCH = "code_name_mismatch"
    NEGATIVE_QTY = "negative_qty"
    INVALID_QTY = "invalid_qty"
    UNKNOWN_UNIT = "unknown_unit"
    UNIT_MISMATCH = "unit_mismatch"
    DUPLICATE_CUSTOMER = "duplicate_customer"
    MISSING_CUSTOMER_CODE = "missing_customer_code"
    MISSING_SHOP_NAME = "missing_shop_name"
    INVALID_CREDIT_TERMS = "invalid_credit_terms"
    UNKNOWN_CUSTOMER = "unknown_customer"
    INVALID_BILL = "invalid_bill"
    INVALID_SALE = "invalid_sale"
    THREAD_NOT_READ = "thread_not_read"
    # warning
    BLANK_CODE = "blank_code"
    DUPLICATE_ROW = "duplicate_row"
    BLANK_RATE = "blank_rate"
    INVALID_RATE = "invalid_rate"
    RATE_MISMATCH = "rate_mismatch"
    BLANK_UNIT = "blank_unit"
    UNKNOWN_SUPPLIER = "unknown_supplier"
    SUPPLIER_MISMATCH = "supplier_mismatch"
    UNCLEAR_PO_REMARK = "unclear_po_remark"
    MISSING_FROM_REGISTER = "missing_from_register"
    COUNT_DATE_MISSING = "count_date_missing"
    INVALID_PHONE = "invalid_phone"
    BALANCE_MISMATCH = "balance_mismatch"
    FUTURE_BILL_DATE = "future_bill_date"
    AMOUNT_MISMATCH = "amount_mismatch"
    UNMATCHED_PRODUCT = "unmatched_product"
    NEEDS_CLARIFICATION = "needs_clarification"
    # info
    SKIPPED_ROW = "skipped_row"
    UNITS_NORMALISED = "units_normalised"
    QTY_AS_TEXT = "qty_as_text"
    NAME_FORMAT = "name_format"
    SUPPLIER_SHORT_NAME = "supplier_short_name"
    OPEN_PO_NOTE = "open_po_note"
    OTHER_SHEET = "other_sheet"
    PHONES_NORMALISED = "phones_normalised"
    PARTY_BY_NAME = "party_by_name"
    DATES_AS_TEXT = "dates_as_text"
    BLANK_RECEIVED = "blank_received"
    PAID_BILL = "paid_bill"
    PRODUCT_MATCHED_BY_LLM = "product_matched_by_llm"
    UNIT_WRITTEN_DIFFERENTLY = "unit_written_differently"

    @property
    def severity(self) -> Severity:
        return SEVERITY[self]


SEVERITY: dict[IssueType, Severity] = {
    **dict.fromkeys(
        (
            IssueType.UNKNOWN_ITEM,
            IssueType.CODE_NAME_MISMATCH,
            IssueType.NEGATIVE_QTY,
            IssueType.INVALID_QTY,
            IssueType.UNKNOWN_UNIT,
            IssueType.UNIT_MISMATCH,
            IssueType.DUPLICATE_CUSTOMER,
            IssueType.MISSING_CUSTOMER_CODE,
            IssueType.MISSING_SHOP_NAME,
            IssueType.INVALID_CREDIT_TERMS,
            IssueType.UNKNOWN_CUSTOMER,
            IssueType.INVALID_BILL,
            IssueType.INVALID_SALE,
            IssueType.THREAD_NOT_READ,
        ),
        "error",
    ),
    **dict.fromkeys(
        (
            IssueType.BLANK_CODE,
            IssueType.DUPLICATE_ROW,
            IssueType.BLANK_RATE,
            IssueType.INVALID_RATE,
            IssueType.RATE_MISMATCH,
            IssueType.BLANK_UNIT,
            IssueType.UNKNOWN_SUPPLIER,
            IssueType.SUPPLIER_MISMATCH,
            IssueType.UNCLEAR_PO_REMARK,
            IssueType.MISSING_FROM_REGISTER,
            IssueType.COUNT_DATE_MISSING,
            IssueType.INVALID_PHONE,
            IssueType.BALANCE_MISMATCH,
            IssueType.FUTURE_BILL_DATE,
            IssueType.AMOUNT_MISMATCH,
            IssueType.UNMATCHED_PRODUCT,
            IssueType.NEEDS_CLARIFICATION,
        ),
        "warning",
    ),
    **dict.fromkeys(
        (
            IssueType.SKIPPED_ROW,
            IssueType.UNITS_NORMALISED,
            IssueType.QTY_AS_TEXT,
            IssueType.NAME_FORMAT,
            IssueType.SUPPLIER_SHORT_NAME,
            IssueType.OPEN_PO_NOTE,
            IssueType.OTHER_SHEET,
            IssueType.PHONES_NORMALISED,
            IssueType.PARTY_BY_NAME,
            IssueType.DATES_AS_TEXT,
            IssueType.BLANK_RECEIVED,
            IssueType.PAID_BILL,
            IssueType.PRODUCT_MATCHED_BY_LLM,
            IssueType.UNIT_WRITTEN_DIFFERENTLY,
        ),
        "info",
    ),
}


@dataclass(frozen=True)
class IssueRecord:
    issue_type: IssueType
    detail: str  # plain-English explanation, including what was done about it
    source_row: int | None = None  # row number in the file; None = about the whole file
    sku: str | None = None  # the product it concerns, when known
    raw: dict[str, Any] | None = None  # the original cell values
    customer_code: str | None = None  # the customer it concerns, when known

    @property
    def severity(self) -> Severity:
        return self.issue_type.severity
