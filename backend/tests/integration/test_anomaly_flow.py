"""Anomalies in the approval flow, end to end with the real sample files and a fake model:
duplicate invoices are blocked, price jumps are shown on "approve for payment" proposals, and
unusually large orders are flagged on "confirm order" proposals."""

import asyncio
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Customer, CustomerOrder, CustomerOrderLine, Product, Upload
from app.llm.invoices import ExtractedInvoice
from app.llm.whatsapp import OrderLine, ProductPick, ProductPicks, ThreadReading
from tests.integration.test_api import upload_form


def _field(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    assert match is not None, pattern
    return match.group(1)


class ReadingModel:
    """Reads the invoice header the way a perfect model would (from the text it is given);
    the item lines are left to code, which reads them from the printed table."""

    def __init__(self, grand_total: str | None = None) -> None:
        self.grand_total = grand_total

    async def __call__(self, messages: Any, schema: type[BaseModel], purpose: str) -> Any:
        if schema is ProductPicks:  # the conduit lines: a sure, checkable pick
            written = re.findall(r'"([^"]+)"', messages[-1]["content"].split("Written items:")[1])
            picks = {
                "PVC Conduit Pipe 20 mm (3 mtr)": "ST-0026",
                "Junction Box 2 way 20mm": "ST-0029",
            }
            return ProductPicks(
                picks=[ProductPick(written=w, sku=picks.get(w), sure=w in picks) for w in written]
            )
        text = messages[-1]["content"]
        return ExtractedInvoice(
            supplier_name=text.splitlines()[0],
            supplier_gstin=_field(text, r"GSTIN:\s*(\S+)"),
            invoice_no=_field(text, r"Invoice No:\s*(\S+)"),
            invoice_date=_field(text, r"Date:\s*(\S+)"),
            lines=[],
            subtotal=_field(text, r"Sub Total\s+Rs ([\d,.]+)"),
            gst_rate_percent="18",
            gst_amount=_field(text, r"GST @18%\s+Rs ([\d,.]+)"),
            grand_total=self.grand_total or _field(text, r"Grand Total\s+Rs ([\d,.]+)"),
            marked_duplicate="DUPLICATE COPY" in text,
            notes=[],
        )


def use_model(model: object) -> None:
    from app.api.deps import get_ask
    from app.main import app

    app.dependency_overrides[get_ask] = lambda: model


async def upload_invoice(client: AsyncClient, path: Path, model: object = None) -> int:
    use_model(model or ReadingModel())
    response = await client.post(
        "/uploads/invoice", files={"file": (path.name, path.read_bytes(), "application/pdf")}
    )
    assert response.status_code == 202, response.text
    upload_id: int = response.json()["upload"]["id"]
    return upload_id


def invoice_proposal(items: list[dict[str, Any]], invoice_no: str) -> dict[str, Any]:
    return next(
        p
        for p in items
        if p["kind"] == "approve_invoice" and p["numbers"]["invoice_no"] == invoice_no
    )


@pytest.fixture
async def invoices(client: AsyncClient, sample_data_dir: Path, seeded: None) -> dict[str, int]:
    """The four sample PDFs, uploaded in name order (the copy of SC-118 comes last)."""
    return {
        path.stem: await upload_invoice(client, path)
        for path in sorted(sample_data_dir.glob("invoice_*.pdf"))
    }


async def test_the_duplicate_invoice_is_blocked_and_reported(
    client: AsyncClient, invoices: dict[str, int]
) -> None:
    statuses = {i["invoice_no"]: [] for i in (await client.get("/invoices")).json()["items"]}
    for invoice in (await client.get("/invoices")).json()["items"]:
        statuses[invoice["invoice_no"]].append(invoice["status"])
    assert sorted(statuses["SC-118"]) == ["awaiting_approval", "duplicate"]

    proposals = (await client.get("/proposals")).json()["items"]
    assert sorted(
        p["numbers"]["invoice_no"] for p in proposals if p["kind"] == "approve_invoice"
    ) == [
        "BL-0874",
        "KC/26-27/2291",
        "SC-118",
    ]  # one proposal for SC-118: the duplicate can never be paid
    copy_issues = (
        await client.get(
            "/issues", params={"upload_id": invoices["invoice_sai_conduits_SC-118_copy"]}
        )
    ).json()["items"]
    assert [i["issue_type"] for i in copy_issues if i["severity"] == "error"] == [
        "duplicate_invoice"
    ]
    by_status = {i["status"]: i for i in (await client.get("/invoices")).json()["items"]}
    assert by_status["duplicate"]["proposal_id"] is None


@pytest.mark.usefixtures("seeded")
async def test_a_copy_without_its_original_can_be_paid_but_is_flagged(
    client: AsyncClient, sample_data_dir: Path
) -> None:
    upload_id = await upload_invoice(
        client, sample_data_dir / "invoice_sai_conduits_SC-118_copy.pdf"
    )

    [invoice] = (await client.get("/invoices")).json()["items"]
    assert (invoice["status"], invoice["marked_duplicate"]) == ("awaiting_approval", True)
    issues = (await client.get("/issues", params={"upload_id": upload_id})).json()["items"]
    [warning] = [i for i in issues if i["issue_type"] == "duplicate_copy_without_original"]
    assert warning["severity"] == "warning"
    assert "no earlier invoice SC-118" in warning["detail"]


async def test_the_price_jump_is_shown_on_the_proposal(
    client: AsyncClient, invoices: dict[str, int]
) -> None:
    proposals = (await client.get("/proposals")).json()["items"]
    brightline = invoice_proposal(proposals, "BL-0874")

    assert (brightline["subject"]["type"], brightline["subject"]["code"]) == ("invoice", "SUP03")
    assert brightline["numbers"]["price_jumps"] == 1 and brightline["numbers"]["needs_owner"]
    bulb = brightline["numbers"]["lines"][0]
    assert (bulb["sku"], bulb["rate"], bulb["last_rate"], bulb["jump_percent"]) == (
        "ST-0017",
        "63.36",
        "48.00",
        "32.0",
    )
    assert bulb["last_rate_from"] == "the product master's cost price"
    assert "LED Bulb 9W Cool White at ₹63.36 against ₹48 (+32.0%)" in brightline["reason"]
    kiran = invoice_proposal(proposals, "KC/26-27/2291")
    assert (kiran["numbers"]["price_jumps"], kiran["numbers"]["ready"]) == (0, True)


async def test_approving_and_rejecting_invoices(
    client: AsyncClient, invoices: dict[str, int]
) -> None:
    proposals = (await client.get("/proposals")).json()["items"]
    approved = await client.post(
        f"/proposals/{invoice_proposal(proposals, 'BL-0874')['id']}/approve"
    )
    rejected = await client.post(
        f"/proposals/{invoice_proposal(proposals, 'KC/26-27/2291')['id']}/reject",
        json={"note": "wrong delivery"},
    )
    assert approved.status_code == rejected.status_code == 200
    by_no = {i["invoice_no"]: i["status"] for i in (await client.get("/invoices")).json()["items"]}
    assert (by_no["BL-0874"], by_no["KC/26-27/2291"]) == ("approved_for_payment", "rejected")


@pytest.mark.usefixtures("seeded")
async def test_an_invoice_whose_figures_dont_add_up_cant_be_approved(
    client: AsyncClient, sample_data_dir: Path
) -> None:
    await upload_invoice(
        client, sample_data_dir / "invoice_kiran_cables_KC-2291.pdf", ReadingModel("1,23,000.00")
    )
    [proposal] = (await client.get("/proposals")).json()["items"]
    assert proposal["numbers"]["ready"] is False

    refused = await client.post(f"/proposals/{proposal['id']}/approve")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "invoice_not_ready"
    assert "the grand total is ₹1,23,000" in refused.json()["error"]["message"]


# Order size -----------------------------------------------------------------------------------

ROYAL_CHAT = (
    b"23/09/26, 9:30 am - Royal Hardware: Bhai 2.5 taar 200 coil urgent chahiye site ke liye"
)


class ChatModel:
    async def __call__(self, messages: Any, schema: type[BaseModel], purpose: str) -> Any:
        return ThreadReading(
            order_lines=[OrderLine(product="2.5 taar", qty=200, unit="coil")],
            enquiries=[],
            unclear=[],
        )


@pytest.fixture
async def history(client: AsyncClient, sample_data_dir: Path, seeded: None) -> AsyncClient:
    for path, name in [
        ("/uploads/customers", "customers.xlsx"),
        ("/uploads/sales", "sales_history_90d.csv"),
    ]:
        content = (sample_data_dir / name).read_bytes()
        assert (await client.post(path, files=upload_form(name, content))).status_code == 201
    return client


async def royal_order(client: AsyncClient, chat: bytes = ROYAL_CHAT) -> dict[str, Any]:
    use_model(ChatModel())
    response = await client.post(
        "/uploads/whatsapp", files={"file": ("chat.txt", chat, "text/plain")}
    )
    assert response.status_code == 202
    proposals = (await client.get("/proposals")).json()["items"]
    return next(p for p in proposals if p["kind"] == "confirm_order")


async def test_an_unusually_large_order_is_flagged_against_the_sales_history(
    history: AsyncClient,
) -> None:
    proposal = await royal_order(history)

    line = proposal["numbers"]["lines"][0]
    assert (line["sku"], line["qty"], line["usual_qty"], line["times_usual"]) == (
        "ST-0003",
        200,
        "1.7",
        "120.0",
    )
    assert line["usual_from"] == "12 sales in the 90-day history"
    assert proposal["numbers"]["needs_owner"] is True
    assert "unusually large, so confirm with the customer (policy 3.1)" in proposal["reason"]


async def test_confirmed_orders_become_the_usual(
    history: AsyncClient, db_session: AsyncSession
) -> None:
    # Decision 036 (option B): once the customer has confirmed WhatsApp orders for the item,
    # those, not the counter-sized sales lines, are what "usual" means.
    royal = await db_session.scalar(select(Customer).where(Customer.code == "CUS010"))
    wire = await db_session.scalar(select(Product).where(Product.sku == "ST-0003"))
    assert royal is not None and wire is not None
    chat = Upload(kind="whatsapp_chat", filename="earlier.txt", status="processed")
    db_session.add(chat)
    await db_session.flush()
    for qty in (150, 180):
        earlier = CustomerOrder(
            upload_id=chat.id,
            customer_id=royal.id,
            sender="Royal Hardware",
            first_sent_at=date(2026, 9, 1),
            source_lines=[1],
            status="confirmed",
        )
        db_session.add(earlier)
        await db_session.flush()
        db_session.add(
            CustomerOrderLine(order_id=earlier.id, product_id=wire.id, written="2.5 taar", qty=qty)
        )
    await db_session.commit()

    proposal = await royal_order(history)

    line = proposal["numbers"]["lines"][0]
    assert line["times_usual"] is None  # 200 against a usual 165: normal for them
    assert proposal["numbers"]["needs_owner"] is False


@pytest.mark.usefixtures("seeded")
async def test_two_copies_uploaded_at_once_still_give_one_payable_invoice(
    client: AsyncClient, sample_data_dir: Path
) -> None:
    original = sample_data_dir / "invoice_sai_conduits_SC-118.pdf"
    copy = sample_data_dir / "invoice_sai_conduits_SC-118_copy.pdf"

    await asyncio.gather(upload_invoice(client, original), upload_invoice(client, copy))

    statuses = sorted(i["status"] for i in (await client.get("/invoices")).json()["items"])
    assert statuses == ["awaiting_approval", "duplicate"]
