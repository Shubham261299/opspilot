from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.domain.invoice_math import InvoiceFigures, InvoiceLineFigures, arithmetic_problems
from app.domain.money import parse_amount

D = Decimal


@pytest.mark.parametrize(
    ("written", "amount"),
    [
        ("1,620.00", D("1620.00")),
        ("Rs 1,04,600.00", D("104600.00")),
        ("₹ 63.36", D("63.36")),
        ("20", D(20)),
        (63.36, D("63.36")),
    ],
)
def test_amounts_are_read_as_written(written: str | float, amount: Decimal) -> None:
    assert parse_amount(written) == amount


@pytest.mark.parametrize("written", [None, "", "90m", "twenty", True])
def test_anything_else_is_not_an_amount(written: str | None) -> None:
    assert parse_amount(written) is None


# Kiran Cables KC/26-27/2291, as printed.
KIRAN = InvoiceFigures(
    lines=[
        InvoiceLineFigures("FR PVC Wire 1.5 sqmm 90m", D(20), D("1620.00"), D("32400.00")),
        InvoiceLineFigures("FR PVC Wire 2.5 sqmm 90m", D(20), D("2580.00"), D("51600.00")),
        InvoiceLineFigures("FR PVC Wire 4.0 sqmm 90m", D(5), D("4120.00"), D("20600.00")),
    ],
    subtotal=D("104600.00"),
    gst_rate_percent=D(18),
    gst_amount=D("18828.00"),
    grand_total=D("123428.00"),
)


def kiran(**changes: Any) -> InvoiceFigures:
    return replace(KIRAN, **changes)


def test_a_correct_invoice_has_no_problems() -> None:
    assert arithmetic_problems(kiran()) == []


def test_brightline_rounding_to_the_paisa_is_fine() -> None:
    invoice = InvoiceFigures(
        lines=[InvoiceLineFigures("LED Bulb 9W", D(200), D("63.36"), D("12672.00"))],
        subtotal=D("12672.00"),
        gst_rate_percent=D(18),
        gst_amount=D("2280.96"),
        grand_total=D("14952.96"),
    )
    assert arithmetic_problems(invoice) == []


@pytest.mark.parametrize(
    ("changes", "says"),
    [
        (
            {"lines": [InvoiceLineFigures("Wire", D(20), D("1620.00"), D("32000.00"))]},
            "20 x ₹1,620 is ₹32,400",
        ),
        ({"subtotal": D("104000.00")}, "the sub total is ₹1,04,000"),
        ({"gst_amount": D("18000.00")}, "GST at 18% of ₹1,04,600 is ₹18,828"),
        ({"grand_total": D("123000.00")}, "the grand total is ₹1,23,000"),
    ],
    ids=["line", "sub total", "gst", "grand total"],
)
def test_every_kind_of_disagreement_is_reported(changes: dict[str, object], says: str) -> None:
    problems = arithmetic_problems(kiran(**changes))
    assert any(says in problem for problem in problems), problems
