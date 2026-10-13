"""Supplier invoices end to end, with a fake language model: PDF upload -> background reading
-> invoice and lines in Postgres -> GET /invoices."""

from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from pypdf import PdfWriter

from app.llm.invoices import ExtractedInvoice, ExtractedLine
from app.llm.whatsapp import ProductPicks

BRIGHTLINE = ExtractedInvoice(
    supplier_name="BRIGHTLINE LED CO.",
    supplier_gstin="27AAAAA1956A1Z3",
    invoice_no="BL-0874",
    invoice_date="19.09.2026",
    lines=[
        ExtractedLine(
            description="LED Bulb 9W Cool White", qty="200", rate="63.36", amount="12,672.00"
        )
    ],
    subtotal="25,622.00",
    gst_rate_percent="18",
    gst_amount="4,611.96",
    grand_total="30,233.96",
    marked_duplicate=False,
    notes=["revised pricing applicable from this invoice"],
)


class FakeModel:
    async def __call__(self, messages: Any, schema: type[BaseModel], purpose: str) -> Any:
        return ProductPicks(picks=[]) if schema is ProductPicks else BRIGHTLINE


@pytest.fixture
def pdf(sample_data_dir: Path) -> bytes:
    return (sample_data_dir / "invoice_brightline_BL-0874.pdf").read_bytes()


async def upload(client: AsyncClient, name: str, content: bytes) -> Any:
    from app.api.deps import get_ask
    from app.main import app

    app.dependency_overrides[get_ask] = FakeModel
    return await client.post("/uploads/invoice", files={"file": (name, content, "application/pdf")})


@pytest.mark.usefixtures("seeded")
async def test_an_invoice_pdf_is_read_checked_and_saved(client: AsyncClient, pdf: bytes) -> None:
    response = await upload(client, "BL-0874.pdf", pdf)

    assert response.status_code == 202
    upload_id = response.json()["upload"]["id"]
    saved = (await client.get(f"/uploads/{upload_id}")).json()
    assert (saved["status"], saved["rows_read"], saved["as_of"]) == ("processed", 3, "2026-09-19")

    [invoice] = (await client.get("/invoices")).json()["items"]
    assert (invoice["supplier_code"], invoice["invoice_no"], invoice["grand_total"]) == (
        "SUP03",
        "BL-0874",
        "30233.96",
    )
    # Lines come from the printed table (all three), not the model's one-line answer.
    assert invoice["lines_read_by"] == "table"
    first = invoice["lines"][0]
    assert (first["sku"], first["rate"], first["cost_price"]) == ("ST-0017", "63.36", "48.00")
    assert len(invoice["lines"]) == 3
    # The price check, as on its proposal: the 9W bulb is 32% above our cost price.
    assert (first["last_rate"], first["jump_percent"]) == ("48.00", "32.0")
    assert invoice["proposal_id"] is not None
    assert (invoice["ready"], invoice["price_jumps"]) == (True, 1)
    # The rules its proposal follows: the price check (with this invoice's jump) and duplicates.
    assert [c["code"] for c in invoice["policy"]] == ["4.1", "4.2"]
    assert invoice["policy"][0]["why"] == "1 rate is more than 10% above the last purchase rate"
    issues = (await client.get("/issues", params={"upload_id": upload_id})).json()["items"]
    assert issues == []  # every figure agrees


@pytest.mark.usefixtures("seeded")
async def test_the_same_pdf_cant_be_uploaded_twice(client: AsyncClient, pdf: bytes) -> None:
    await upload(client, "BL-0874.pdf", pdf)
    again = await upload(client, "copy.pdf", pdf)
    assert again.status_code == 409


async def test_a_pdf_without_text_is_refused_and_recorded(client: AsyncClient) -> None:
    writer, buffer = PdfWriter(), BytesIO()
    writer.add_blank_page(width=595, height=842)
    writer.write(buffer)
    response = await upload(client, "scan.pdf", buffer.getvalue())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_text"


async def test_only_pdfs_are_accepted(client: AsyncClient) -> None:
    response = await upload(client, "invoice.txt", b"Invoice No: 1")
    assert response.status_code == 415
