"""Eval: supplier invoice reading, scored against the answer key.

Runs the same code the app runs (intake/invoice_pdf.py + intake/invoices.py) on each sample
invoice PDF and compares what was read with `expected_invoices` in the answer key: invoice
number, supplier, date, every line's product, quantity and rate, the totals, and whether the
invoice says it is a duplicate. Money is compared exactly, to the paisa.
"""

from decimal import Decimal
from typing import Any

from app.intake.errors import IntakeError
from app.intake.invoice_pdf import pdf_text
from app.intake.invoices import InvoiceReading, read_invoice
from app.intake.issues import IssueType
from evals.common import DATA, CountingAsk, Report, as_of, load_answer_key, load_catalog

SUITE = "invoices"


async def run(ask: CountingAsk) -> Report:
    key = load_answer_key()
    catalog, today = load_catalog(), as_of(key)
    rows: list[dict[str, Any]] = []
    for expected in key["expected_invoices"]:
        text = pdf_text((DATA / expected["file"]).read_bytes())
        try:
            reading = await read_invoice(text, catalog, ask, today)
        except IntakeError as error:
            rows.append(not_read(expected, error.code))
            continue
        rows.append(score_invoice(expected, reading))
    return Report(summarise(rows, ask.calls), rows)


def not_read(expected: dict[str, Any], code: str) -> dict[str, Any]:
    return {
        "file": expected["file"],
        "all_right": False,
        "not_read": code,
        "lines_exact": 0,
        "lines_expected": len(expected["lines"]),
        "problems": ["invoice not read"],
    }


def score_invoice(expected: dict[str, Any], reading: InvoiceReading) -> dict[str, Any]:
    problems: list[str] = []

    def check(name: str, got: object, want: object) -> None:
        if got != want:
            problems.append(f"{name}: read {got!r}, expected {want!r}")

    check("invoice_no", reading.invoice_no, expected["invoice_no"])
    check("supplier_code", reading.supplier_code, expected["supplier_code"])
    check(
        "invoice_date",
        reading.invoice_date.isoformat() if reading.invoice_date else None,
        expected["invoice_date"],
    )
    for name in ("subtotal", "gst_amount", "grand_total"):
        check(name, getattr(reading, name), Decimal(str(expected[name])))
    check("marked_duplicate", reading.marked_duplicate, expected["marked_duplicate"])

    want_lines = {
        (ln["sku"], Decimal(str(ln["qty"])), Decimal(str(ln["rate"]))) for ln in expected["lines"]
    }
    got_lines = {(ln.sku, ln.qty, ln.rate) for ln in reading.lines}
    for sku, qty, rate in sorted(want_lines - got_lines, key=str):
        problems.append(f"line {sku} x {qty} @ {rate} not read as expected")
    for sku, qty, rate in sorted(got_lines - want_lines, key=str):
        problems.append(f"unexpected line {sku} x {qty} @ {rate}")
    arithmetic = sum(1 for i in reading.issues if i.issue_type is IssueType.INVOICE_ARITHMETIC)
    if arithmetic:
        problems.append(f"{arithmetic} arithmetic problem(s) reported on a consistent invoice")
    return {
        "file": expected["file"],
        "all_right": not problems,
        "lines_exact": len(want_lines & got_lines),
        "lines_expected": len(want_lines),
        "lines_read_by": reading.lines_read_by,
        "problems": problems,
    }


def summarise(rows: list[dict[str, Any]], model_calls: int) -> dict[str, Any]:
    return {
        "model_calls": model_calls,
        "invoices_fully_right": sum(r["all_right"] for r in rows),
        "invoices_expected": len(rows),
        "lines_exact": sum(r["lines_exact"] for r in rows),
        "lines_expected": sum(r["lines_expected"] for r in rows),
        "invoices_not_read": sum(1 for r in rows if r.get("not_read")),
        "lines_read_from_table": sum(1 for r in rows if r.get("lines_read_by") == "table"),
    }
