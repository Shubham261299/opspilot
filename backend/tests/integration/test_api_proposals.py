"""Proposals end to end: the four sample files -> run checks -> approve / reject -> audit."""

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Customer, PaymentReminder, PurchaseOrder
from tests.integration.test_api import count, upload_form

SAMPLE_TODAY = date(2026, 9, 24)  # "today" in the sample data
ANSWER_KEY = json.loads(
    (Path(__file__).resolve().parents[3] / "sample_data" / "answer_key.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture
async def loaded(client: AsyncClient, sample_data_dir: Path, seeded: None) -> AsyncClient:
    """The client, with all four sample files uploaded and "today" set to the data's date."""
    from app.api.deps import get_today
    from app.main import app

    app.dependency_overrides[get_today] = lambda: SAMPLE_TODAY
    files = [
        ("/uploads/stock", "stock_register.xlsx"),
        ("/uploads/customers", "customers.xlsx"),
        ("/uploads/dues", "outstanding_dues.xlsx"),
        ("/uploads/sales", "sales_history_90d.csv"),
    ]
    for path, name in files:
        content = (sample_data_dir / name).read_bytes()
        response = await client.post(path, files=upload_form(name, content))
        assert response.status_code == 201, response.text
    return client


async def run(client: AsyncClient) -> dict[str, Any]:
    response = await client.post("/proposals/run")
    assert response.status_code == 200
    return response.json()


async def pending(client: AsyncClient) -> list[dict[str, Any]]:
    return (await client.get("/proposals")).json()["items"]


def find(items: list[dict[str, Any]], kind: str, code: str) -> dict[str, Any]:
    return next(p for p in items if p["kind"] == kind and p["subject"]["code"] == code)


async def test_without_data_nothing_is_proposed_and_the_reason_is_given(
    client: AsyncClient,
) -> None:
    body = await run(client)
    assert (body["created"], body["pending"]) == (0, 0)
    assert len(body["not_checked"]) == 2


async def test_checks_propose_exactly_what_the_answer_key_expects(loaded: AsyncClient) -> None:
    body = await run(loaded)

    items = await pending(loaded)
    reorders = {p["subject"]["code"]: p for p in items if p["kind"] == "reorder"}
    assert {sku: p["numbers"]["qty"] for sku, p in reorders.items()} == {
        e["sku"]: e["reorder_qty"] for e in ANSWER_KEY["expected_reorders"]
    }
    actions = {
        p["subject"]["code"]: "HOLD_NEW_ORDERS" if p["kind"] == "hold_orders" else "SEND_REMINDER"
        for p in items
        if p["subject"]["type"] == "customer"
    }
    assert actions == {
        e["customer_id"]: e["expected_action"] for e in ANSWER_KEY["expected_payment_actions"]
    }
    assert body["created"] == body["pending"] == 18
    assert body["not_checked"] == [
        "Reorders: no trusted stock count for ST-0040 (see the Issues page)."
    ]


async def test_a_proposal_explains_itself_with_its_numbers(loaded: AsyncClient) -> None:
    await run(loaded)
    proposal = find(await pending(loaded), "reorder", "ST-0002")

    assert proposal["numbers"]["est_cost"] == "178200.00"
    assert proposal["numbers"]["needs_owner"] is True
    assert "Order 110 coils (11 packs of 10) from Kiran Cables Pvt Ltd" in proposal["reason"]
    assert "₹1,78,200" in proposal["reason"]
    assert proposal["basis"]["today"] == "2026-09-24"


async def test_running_checks_again_changes_nothing(loaded: AsyncClient) -> None:
    first = await run(loaded)
    second = await run(loaded)
    assert (second["created"], second["superseded"], second["unchanged"]) == (0, 0, 18)
    assert second["pending"] == first["pending"]


async def test_approving_a_reorder_creates_a_purchase_order_and_an_audit_row(
    loaded: AsyncClient, db_session: AsyncSession
) -> None:
    await run(loaded)
    proposal = find(await pending(loaded), "reorder", "ST-0002")

    response = await loaded.post(
        f"/proposals/{proposal['id']}/approve", json={"note": "ok, order it"}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["decision_note"]) == ("approved", "ok, order it")
    [order] = (await loaded.get("/purchase-orders")).json()["items"]
    assert order["id"] == body["purchase_order_id"]
    assert (order["supplier"]["code"], order["total"]) == ("SUP01", "178200.00")
    assert order["lines"][0]["qty"] == 110
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.action == "proposal.approve"))
    assert audit is not None and audit.entity_id == str(proposal["id"])
    assert audit.before is not None and audit.before["status"] == "pending"
    assert audit.after is not None and audit.after["purchase_order_id"] == order["id"]

    # The order now counts as "on order", so the next run doesn't propose it again.
    products = (await loaded.get("/products")).json()["items"]
    assert next(p for p in products if p["sku"] == "ST-0002")["on_order_qty"] == 110
    again = await run(loaded)
    assert again["created"] == 0
    assert all(p["subject"]["code"] != "ST-0002" for p in await pending(loaded))


async def test_a_proposal_can_only_be_decided_once(
    loaded: AsyncClient, db_session: AsyncSession
) -> None:
    await run(loaded)
    proposal = find(await pending(loaded), "reorder", "ST-0002")
    url = f"/proposals/{proposal['id']}/approve"

    # Two clicks at the same moment: the row lock makes the second one wait, then fail.
    first, second = await asyncio.gather(loaded.post(url), loaded.post(url))

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    loser = first if first.status_code == 409 else second
    assert loser.json()["error"]["code"] == "proposal_already_decided"
    assert await count(db_session, PurchaseOrder) == 1


async def test_approving_a_hold_puts_the_customer_on_hold(
    loaded: AsyncClient, db_session: AsyncSession
) -> None:
    await run(loaded)
    proposal = find(await pending(loaded), "hold_orders", "CUS010")

    await loaded.post(f"/proposals/{proposal['id']}/approve")

    customer = await db_session.scalar(select(Customer).where(Customer.code == "CUS010"))
    assert customer is not None and customer.on_hold
    assert customer.hold_reason == proposal["reason"]
    again = await run(loaded)
    assert again["created"] == 0  # already on hold: no new hold proposal


async def test_approving_a_reminder_prepares_a_polite_message(
    loaded: AsyncClient, db_session: AsyncSession
) -> None:
    await run(loaded)
    proposal = find(await pending(loaded), "payment_reminder", "CUS001")

    body = (await loaded.post(f"/proposals/{proposal['id']}/approve")).json()

    message = body["reminder_message"]
    assert message.startswith("Namaste Ramesh Patil ji")
    assert "ST/5104" in message and "₹25,500" in message
    assert "Om Sai" not in message  # never another customer's details (policy 2.5)
    reminder = await db_session.scalar(select(PaymentReminder))
    assert reminder is not None and reminder.status == "ready"  # sending comes later
    again = await run(loaded)
    assert (again["created"], again["already_decided"]) == (0, 1)  # not proposed twice


async def test_rejecting_records_the_note_and_does_nothing_else(
    loaded: AsyncClient, db_session: AsyncSession
) -> None:
    await run(loaded)
    proposal = find(await pending(loaded), "reorder", "ST-0047")

    body = (
        await loaded.post(
            f"/proposals/{proposal['id']}/reject", json={"note": "  supplier closed this week "}
        )
    ).json()

    assert (body["status"], body["decision_note"], body["purchase_order_id"]) == (
        "rejected",
        "supplier closed this week",
        None,
    )
    assert await count(db_session, PurchaseOrder) == 0
    history = (await loaded.get("/proposals", params={"status": "rejected"})).json()["items"]
    assert [p["id"] for p in history] == [proposal["id"]]
    again = await run(loaded)
    assert (again["created"], again["already_decided"]) == (0, 1)  # same situation, not re-asked


async def test_an_unknown_proposal_is_a_404(client: AsyncClient) -> None:
    response = await client.post("/proposals/999/approve")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "proposal_not_found"
