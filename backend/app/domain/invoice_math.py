"""Checking a supplier invoice's arithmetic, so a misread or a supplier's mistake is caught.

The language model reads the figures off the PDF; code checks that they agree:
- each line: qty x rate = amount
- the lines add up to the subtotal
- GST is the stated rate of the subtotal
- subtotal + GST = grand total
Amounts are compared to the paisa (rounded half up), which is how invoices are printed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.money import format_inr

PAISA = Decimal("0.01")


@dataclass(frozen=True)
class InvoiceLineFigures:
    description: str
    qty: Decimal
    rate: Decimal
    amount: Decimal


@dataclass(frozen=True)
class InvoiceFigures:
    lines: Sequence[InvoiceLineFigures]
    subtotal: Decimal
    gst_rate_percent: Decimal | None  # e.g. 18; None if the invoice doesn't state it
    gst_amount: Decimal
    grand_total: Decimal


def paise(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def arithmetic_problems(invoice: InvoiceFigures) -> list[str]:
    """Plain-language problems; an empty list means every figure agrees."""
    problems = []
    for number, line in enumerate(invoice.lines, start=1):
        expected = paise(line.qty * line.rate)
        if paise(line.amount) != expected:
            problems.append(
                f"Line {number} ({line.description}): {line.qty} x {format_inr(line.rate)} is "
                f"{format_inr(expected)}, but the invoice says {format_inr(line.amount)}."
            )
    lines_total = paise(sum((line.amount for line in invoice.lines), start=Decimal(0)))
    if lines_total != paise(invoice.subtotal):
        problems.append(
            f"The lines add up to {format_inr(lines_total)}, but the sub total is "
            f"{format_inr(invoice.subtotal)}."
        )
    if invoice.gst_rate_percent is not None:
        expected_gst = paise(invoice.subtotal * invoice.gst_rate_percent / 100)
        if expected_gst != paise(invoice.gst_amount):
            problems.append(
                f"GST at {invoice.gst_rate_percent}% of {format_inr(invoice.subtotal)} is "
                f"{format_inr(expected_gst)}, but the invoice says "
                f"{format_inr(invoice.gst_amount)}."
            )
    expected_total = paise(invoice.subtotal + invoice.gst_amount)
    if expected_total != paise(invoice.grand_total):
        problems.append(
            f"Sub total + GST is {format_inr(expected_total)}, but the grand total is "
            f"{format_inr(invoice.grand_total)}."
        )
    return problems
