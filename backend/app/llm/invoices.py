"""Prompt and output schema for reading a supplier invoice's text.

The model copies figures exactly as printed (as text, so nothing is rounded or reformatted
on the way); code then parses them and checks that they add up (domain/invoice_math.py).
"""

from pydantic import BaseModel, Field

Message = dict[str, str]


class ExtractedLine(BaseModel):
    description: str = Field(description="The item description exactly as printed")
    qty: str = Field(description="The quantity as printed")
    rate: str = Field(description="The rate per unit as printed")
    amount: str = Field(description="The line amount as printed")


class ExtractedInvoice(BaseModel):
    supplier_name: str
    supplier_gstin: str | None
    invoice_no: str
    invoice_date: str = Field(description="As printed, e.g. 19.09.2026")
    lines: list[ExtractedLine]
    subtotal: str
    gst_rate_percent: str | None = Field(description="e.g. 18, if the invoice states it")
    gst_amount: str
    grand_total: str
    marked_duplicate: bool = Field(description="True if the invoice says it is a duplicate copy")
    notes: list[str] = Field(description="Other remarks printed on the invoice")


_SYSTEM = """You read the text of a supplier's tax invoice sent to Sharma Traders, an \
electrical distributor in Pune, and return its contents as JSON.

Copy every figure EXACTLY as printed, as text, with its commas and decimals ("1,620.00"). Do \
not calculate, round, correct or add anything: if a figure looks wrong, still copy it as \
printed. One entry in "lines" per item row. "notes" holds any other remark (for example \
"revised pricing"). Set marked_duplicate to true only if the invoice says it is a duplicate \
copy."""

_EXAMPLE_TEXT = """ACME WIRING SUPPLIES
GSTIN: 27BBBBB0000B1Z5
TAX INVOICE
Invoice No: AW/101
Date: 03.08.2026
# Description Qty Rate Amount
1 Fan Regulator Modular 10 210.00 2,100.00
2 Bell Push Modular 25 40.00 1,000.00
Sub Total Rs 3,100.00
GST @18% Rs 558.00
Grand Total Rs 3,658.00
Note: delivery by road."""

_EXAMPLE_ANSWER = ExtractedInvoice(
    supplier_name="ACME WIRING SUPPLIES",
    supplier_gstin="27BBBBB0000B1Z5",
    invoice_no="AW/101",
    invoice_date="03.08.2026",
    lines=[
        ExtractedLine(
            description="Fan Regulator Modular", qty="10", rate="210.00", amount="2,100.00"
        ),
        ExtractedLine(description="Bell Push Modular", qty="25", rate="40.00", amount="1,000.00"),
    ],
    subtotal="3,100.00",
    gst_rate_percent="18",
    gst_amount="558.00",
    grand_total="3,658.00",
    marked_duplicate=False,
    notes=["delivery by road"],
)


def read_invoice_messages(text: str) -> list[Message]:
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _EXAMPLE_TEXT},
        {"role": "assistant", "content": _EXAMPLE_ANSWER.model_dump_json()},
        {"role": "user", "content": text},
    ]
