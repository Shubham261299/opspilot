"""Reading supplier invoices: PDF text, table rows, and the reader with a fake model."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from pypdf import PdfWriter

from app.domain.catalog import Catalog
from app.intake.errors import IntakeError
from app.intake.invoice_pdf import pdf_text
from app.intake.invoices import read_invoice, rows_from_table
from app.intake.issues import IssueType
from app.llm.client import LlmError
from app.llm.invoices import ExtractedInvoice, ExtractedLine
from app.llm.whatsapp import ProductPick, ProductPicks

TODAY = date(2026, 9, 24)


@pytest.mark.parametrize(
    ("name", "invoice_no", "rows"),
    [
        ("invoice_brightline_BL-0874.pdf", "BL-0874", 3),
        ("invoice_kiran_cables_KC-2291.pdf", "KC/26-27/2291", 3),
        ("invoice_sai_conduits_SC-118.pdf", "SC-118", 3),
        ("invoice_sai_conduits_SC-118_copy.pdf", "SC-118", 3),
    ],
)
def test_the_sample_pdfs_have_text_and_table_rows(
    sample_data_dir: Path, name: str, invoice_no: str, rows: int
) -> None:
    text = pdf_text((sample_data_dir / name).read_bytes())
    assert invoice_no in text
    assert len(rows_from_table(text)) == rows


def test_a_table_row_is_read_exactly_as_printed(sample_data_dir: Path) -> None:
    text = pdf_text((sample_data_dir / "invoice_kiran_cables_KC-2291.pdf").read_bytes())
    assert rows_from_table(text)[0] == (
        1,
        "FR PVC Wire 1.5 sqmm 90m",
        Decimal(20),
        Decimal("1620.00"),
        Decimal("32400.00"),
    )


def test_a_file_that_isnt_a_pdf_is_refused() -> None:
    with pytest.raises(IntakeError) as error:
        pdf_text(b"not a pdf at all")
    assert error.value.code == "unreadable_file"


def test_a_pdf_without_text_is_refused() -> None:
    writer, buffer = PdfWriter(), BytesIO()
    writer.add_blank_page(width=595, height=842)  # like a scanned page: no text to read
    writer.write(buffer)
    with pytest.raises(IntakeError) as error:
        pdf_text(buffer.getvalue())
    assert error.value.code == "no_text"


# The reader, with a fake model -------------------------------------------------------------

KIRAN_TEXT = """KIRAN CABLES PVT LTD
TAX INVOICE   Invoice No: KC/26-27/2291
#   Description   Qty   Rate   Amount
1   FR PVC Wire 1.5 sqmm 90m   20   1,620.00   32,400.00
2   FR PVC Wire 2.5 sqmm 90m   20   2,580.00   51,600.00
   Sub Total   Rs 84,000.00
   GST @18%   Rs 15,120.00
   Grand Total   Rs 99,120.00"""


def extracted(lines: list[ExtractedLine], **fields: Any) -> ExtractedInvoice:
    values: dict[str, Any] = {
        "supplier_name": "KIRAN CABLES PVT LTD",
        "supplier_gstin": "27AAAAA1913A1Z8",
        "invoice_no": "KC/26-27/2291",
        "invoice_date": "12.09.2026",
        "lines": lines,
        "subtotal": "84,000.00",
        "gst_rate_percent": "18",
        "gst_amount": "15,120.00",
        "grand_total": "99,120.00",
        "marked_duplicate": False,
        "notes": [],
    }
    return ExtractedInvoice(**(values | fields))


# What the 7b model really returned for Kiran: "90m" (from the name) as the quantity.
MISREAD = [
    ExtractedLine(description="FR PVC Wire 1.5 sqmm 90m", qty="90m", rate="20", amount="32,400.00"),
    ExtractedLine(
        description="FR PVC Wire 2.5 sqmm 90m", qty="90m", rate="2,580.00", amount="51,600.00"
    ),
]


class FakeModel:
    def __init__(
        self, answer: ExtractedInvoice | Exception, picks: list[ProductPick] | None = None
    ):
        self.answer, self.picks = answer, picks or []

    async def __call__(self, messages: Any, schema: type[BaseModel], purpose: str) -> Any:
        if schema is ProductPicks:
            return ProductPicks(picks=self.picks)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


async def test_table_rows_read_by_code_win_over_a_misread(catalog: Catalog) -> None:
    reading = await read_invoice(KIRAN_TEXT, catalog, FakeModel(extracted(MISREAD)), TODAY)

    assert reading.lines_read_by == "table"
    assert [(line.sku, line.qty, line.rate) for line in reading.lines] == [
        ("ST-0002", Decimal(20), Decimal("1620.00")),
        ("ST-0003", Decimal(20), Decimal("2580.00")),
    ]
    assert (reading.supplier_code, reading.invoice_date) == ("SUP01", date(2026, 9, 12))
    assert reading.issues == []


async def test_without_a_readable_table_the_models_lines_are_checked(catalog: Catalog) -> None:
    text = KIRAN_TEXT.replace("   ", " ")  # no column gaps: code can't read the rows
    reading = await read_invoice(text, catalog, FakeModel(extracted(MISREAD)), TODAY)

    assert reading.lines_read_by == "model"
    assert reading.lines == []  # "90m" isn't a quantity: neither line was saved
    types = [issue.issue_type for issue in reading.issues]
    assert types.count(IssueType.INVOICE_FIGURE_UNREADABLE) == 2
    assert IssueType.INVOICE_ARITHMETIC in types


async def test_an_unknown_supplier_and_a_model_matched_product(catalog: Catalog) -> None:
    lines = [ExtractedLine(description="Bend 20 mm pipe fitting", qty="10", rate="6", amount="60")]
    answer = extracted(
        lines, supplier_name="New Pipes Co", subtotal="60", gst_amount="10.80", grand_total="70.80"
    )
    model = FakeModel(
        answer, [ProductPick(written="Bend 20 mm pipe fitting", sku="ST-0028", sure=True)]
    )

    reading = await read_invoice("no table here", catalog, model, TODAY)

    assert reading.supplier_code is None
    assert [(line.sku, line.matched_on) for line in reading.lines] == [("ST-0028", "model")]
    assert {i.issue_type for i in reading.issues} == {
        IssueType.UNKNOWN_SUPPLIER,
        IssueType.PRODUCT_MATCHED_BY_LLM,
    }


async def test_when_the_model_fails_the_invoice_is_not_guessed(catalog: Catalog) -> None:
    with pytest.raises(IntakeError) as error:
        await read_invoice(KIRAN_TEXT, catalog, FakeModel(LlmError("unavailable", "off")), TODAY)
    assert error.value.code == "not_read"
