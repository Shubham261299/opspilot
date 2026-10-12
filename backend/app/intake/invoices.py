"""A supplier invoice's text -> a checked invoice: figures, supplier, products, issues.

- the model copies the invoice's contents, figures as printed (app/llm/invoices.py);
- code parses every figure and checks the arithmetic (domain/invoice_math.py);
- code matches the supplier (full name, code or short name) and each item: exact name or
  alias, then the same words in another order, then the model picks from the catalogue for
  what's left, and code checks every pick (intake/product_picks.py).
Anything that doesn't fit becomes an issue; nothing is corrected silently.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.domain.catalog import Catalog
from app.domain.dates import parse_day_first
from app.domain.invoice_math import (
    InvoiceFigures,
    InvoiceLineFigures,
    arithmetic_problems,
    paise,
)
from app.domain.matching import match_product_by_words, resolve_supplier
from app.domain.money import parse_amount
from app.intake.errors import IntakeError
from app.intake.issues import IssueRecord, IssueType
from app.intake.product_picks import Ask, pick_products
from app.llm.client import LlmError
from app.llm.invoices import ExtractedInvoice, read_invoice_messages


@dataclass(frozen=True)
class InvoiceLine:
    number: int  # position on the invoice, from 1
    description: str
    qty: Decimal
    rate: Decimal
    amount: Decimal
    sku: str | None  # None = not matched; a human chooses
    matched_on: str | None  # name, alias, same words, model


@dataclass
class InvoiceReading:
    supplier_code: str | None
    supplier_name: str  # as printed
    supplier_gstin: str | None
    invoice_no: str
    invoice_date: date | None
    lines: list[InvoiceLine]
    subtotal: Decimal
    gst_rate_percent: Decimal | None
    gst_amount: Decimal
    grand_total: Decimal
    marked_duplicate: bool
    notes: list[str]
    lines_read_by: str = "model"  # "table": read by code from the printed table
    issues: list[IssueRecord] = field(default_factory=list)


async def read_invoice(text: str, catalog: Catalog, ask: Ask, today: date) -> InvoiceReading:
    try:
        extracted = await ask(read_invoice_messages(text), ExtractedInvoice, "invoice_read")
    except LlmError as error:
        raise IntakeError(
            "not_read", f"The language model couldn't read the invoice ({error.message})."
        ) from error

    totals = {
        name: parse_amount(getattr(extracted, name))
        for name in ("subtotal", "gst_amount", "grand_total")
    }
    missing = [name.replace("_", " ") for name, value in totals.items() if value is None]
    if missing or not extracted.invoice_no.strip():
        raise IntakeError(
            "not_read",
            "The invoice number or totals couldn't be read"
            + (f" ({', '.join(missing)})" if missing else "")
            + "; enter this invoice by hand.",
        )

    supplier = resolve_supplier(extracted.supplier_name, catalog)
    reading = InvoiceReading(
        supplier_code=supplier.code if supplier else None,
        supplier_name=extracted.supplier_name.strip(),
        supplier_gstin=(extracted.supplier_gstin or "").strip() or None,
        invoice_no=extracted.invoice_no.strip(),
        invoice_date=parse_day_first(extracted.invoice_date, today),
        lines=[],
        subtotal=totals["subtotal"] or Decimal(0),
        gst_rate_percent=parse_amount(extracted.gst_rate_percent),
        gst_amount=totals["gst_amount"] or Decimal(0),
        grand_total=totals["grand_total"] or Decimal(0),
        marked_duplicate=extracted.marked_duplicate,
        notes=extracted.notes,
    )
    if supplier is None:
        reading.issues.append(
            IssueRecord(
                IssueType.UNKNOWN_SUPPLIER,
                f"Supplier '{extracted.supplier_name}' is not in the supplier list; the invoice "
                "was saved, but it can't be approved for payment until the supplier is known.",
            )
        )
    if reading.invoice_date is None:
        reading.issues.append(
            IssueRecord(
                IssueType.INVOICE_DATE_UNREADABLE,
                f"The invoice date '{extracted.invoice_date}' couldn't be read.",
            )
        )

    # Code first: item rows read straight from the printed table, used only when every row
    # checks out and they add up to the sub total. Otherwise the model's lines (still checked).
    figures = rows_from_table(text)
    if _consistent(figures, reading.subtotal):
        reading.lines_read_by = "table"
    else:
        figures = _line_figures(extracted, reading)
    await _match_lines(figures, catalog, ask, reading)
    for problem in arithmetic_problems(
        InvoiceFigures(
            lines=[InvoiceLineFigures(f[1], f[2], f[3], f[4]) for f in figures],
            subtotal=reading.subtotal,
            gst_rate_percent=reading.gst_rate_percent,
            gst_amount=reading.gst_amount,
            grand_total=reading.grand_total,
        )
    ):
        reading.issues.append(IssueRecord(IssueType.INVOICE_ARITHMETIC, problem))
    return reading


# "1   FR PVC Wire 1.5 sqmm 90m   20   1,620.00   32,400.00": number, description, qty, rate,
# amount, separated by runs of spaces (pypdf's layout mode keeps a row on one line).
_NUM = r"\d[\d,]*(?:\.\d+)?"
_ROW = re.compile(
    rf"^\s*(\d{{1,3}})\s{{2,}}(.+?)\s{{2,}}({_NUM})\s{{2,}}({_NUM})\s{{2,}}({_NUM})\s*$"
)


def rows_from_table(text: str) -> list[tuple[int, str, Decimal, Decimal, Decimal]]:
    """Item rows exactly as printed, when the invoice is laid out as a simple table."""
    rows = []
    for line in text.splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        number, description, *figures = match.groups()
        qty, rate, amount = (parse_amount(f) for f in figures)
        if qty is not None and rate is not None and amount is not None:
            rows.append((int(number), description.strip(), qty, rate, amount))
    return rows


def _consistent(rows: list[tuple[int, str, Decimal, Decimal, Decimal]], subtotal: Decimal) -> bool:
    """Every row's qty x rate = amount, and together they make the sub total."""
    return (
        bool(rows)
        and all(paise(qty * rate) == paise(amount) for _, _, qty, rate, amount in rows)
        and paise(sum((row[4] for row in rows), start=Decimal(0))) == paise(subtotal)
    )


def _line_figures(
    extracted: ExtractedInvoice, reading: InvoiceReading
) -> list[tuple[int, str, Decimal, Decimal, Decimal]]:
    """(number, description, qty, rate, amount) for each line whose figures can be read."""
    figures = []
    for number, line in enumerate(extracted.lines, start=1):
        qty, rate, amount = (
            parse_amount(line.qty),
            parse_amount(line.rate),
            parse_amount(line.amount),
        )
        if qty is None or rate is None or amount is None:
            reading.issues.append(
                IssueRecord(
                    IssueType.INVOICE_FIGURE_UNREADABLE,
                    f"Line {number} ('{line.description}'): the quantity, rate or amount "
                    f"('{line.qty}', '{line.rate}', '{line.amount}') couldn't be read, so the "
                    "line was not saved.",
                )
            )
            continue
        figures.append((number, line.description.strip(), qty, rate, amount))
    return figures


async def _match_lines(
    figures: list[tuple[int, str, Decimal, Decimal, Decimal]],
    catalog: Catalog,
    ask: Ask,
    reading: InvoiceReading,
) -> None:
    matched: dict[str, tuple[str, str]] = {}
    for _, description, *_rest in figures:
        match = match_product_by_words(description, catalog)
        if match is not None:
            matched[description] = (match.sku, match.matched_on)
    leftovers = [f[1] for f in figures if f[1] not in matched]
    for written, sku in (await pick_products(leftovers, catalog, ask, "invoice_match")).items():
        matched[written] = (sku, "model")
        reading.issues.append(
            IssueRecord(
                IssueType.PRODUCT_MATCHED_BY_LLM,
                f"'{written}' was matched to {sku} '{catalog.products[sku].name}' by the "
                "language model; check it when approving the invoice.",
                sku=sku,
            )
        )
    for number, description, qty, rate, amount in figures:
        sku, how = matched.get(description, (None, None))
        if sku is None:
            reading.issues.append(
                IssueRecord(
                    IssueType.UNMATCHED_PRODUCT,
                    f"Line {number} '{description}' matches no product for sure; choose it "
                    "before approving.",
                )
            )
        elif reading.supplier_code and catalog.products[sku].supplier_code != reading.supplier_code:
            reading.issues.append(
                IssueRecord(
                    IssueType.SUPPLIER_MISMATCH,
                    f"Line {number}: {sku} is normally bought from "
                    f"{catalog.products[sku].supplier_code}, not {reading.supplier_code}.",
                    sku=sku,
                )
            )
        reading.lines.append(InvoiceLine(number, description, qty, rate, amount, sku, how))
