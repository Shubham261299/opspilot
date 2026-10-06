"""WhatsApp orders end to end, with a fake language model: upload -> background reading ->
orders, enquiries and "confirm order" proposals -> fix a line -> approve / reject."""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.llm.client import LlmError
from app.llm.whatsapp import OrderLine, ProductPicks, ThreadReading
from tests.integration.test_api import upload_form

CHAT = "\n".join(
    [
        "22/09/26, 9:00 am - Messages and calls are end-to-end encrypted.",
        "22/09/26, 9:13 am - Ramesh Electricals: 20 box 1.5mm wire aur 10 pkt gitti",
        "22/09/26, 10:05 am - Om Sai Hardware: 6a switch 200, ye wala panel 20",
        "22/09/26, 4:48 pm - Ramesh Electricals: 1.5 wala 20 nahi 15 karo",
        "23/09/26, 5:55 pm - A1 Electric Store: Pls send rate list for LED panels",
    ]
).encode()

# What the fake model answers, thread by thread (Ramesh, Om Sai, A1), in chat order.
READINGS = [
    ThreadReading(
        order_lines=[
            OrderLine(product="1.5mm wire", qty=15, unit="box"),
            OrderLine(product="gitti", qty=10, unit="pkt"),
        ],
        enquiries=[],
        unclear=[],
    ),
    ThreadReading(
        order_lines=[OrderLine(product="6a switch", qty=200), OrderLine(product="panel", qty=20)],
        enquiries=[],
        unclear=[],
    ),
    ThreadReading(order_lines=[], enquiries=["Pls send rate list for LED panels"], unclear=[]),
]


class FakeModel:
    def __init__(self, readings: list[ThreadReading | Exception]) -> None:
        self.readings = list(readings)

    async def __call__(self, messages: Any, schema: type[BaseModel], purpose: str) -> Any:
        if schema is ProductPicks:  # "panel" could be several products: the model isn't sure
            return ProductPicks(picks=[])
        answer = self.readings.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def use_model(model: FakeModel) -> None:
    from app.api.deps import get_ask
    from app.main import app

    app.dependency_overrides[get_ask] = lambda: model


@pytest.fixture
async def customers(client: AsyncClient, sample_data_dir: Path, seeded: None) -> AsyncClient:
    content = (sample_data_dir / "customers.xlsx").read_bytes()
    await client.post("/uploads/customers", files=upload_form("customers.xlsx", content))
    return client


async def upload_chat(client: AsyncClient, readings: list[Any] = READINGS) -> dict[str, Any]:
    use_model(FakeModel(readings))
    response = await client.post(
        "/uploads/whatsapp", files={"file": ("chat.txt", CHAT, "text/plain")}
    )
    assert response.status_code == 202, response.text
    return response.json()


def proposal_for(items: list[dict[str, Any]], code: str) -> dict[str, Any]:
    return next(p for p in items if p["subject"]["code"] == code)


async def test_a_chat_becomes_orders_proposals_and_enquiries(customers: AsyncClient) -> None:
    accepted = await upload_chat(customers)

    assert accepted["upload"]["status"] == "processing"  # the answer comes before the reading
    upload = (await customers.get(f"/uploads/{accepted['upload']['id']}")).json()
    assert (upload["status"], upload["rows_read"], upload["rows_loaded"]) == ("processed", 4, 2)

    orders = (await customers.get("/orders")).json()["items"]
    ramesh = next(o for o in orders if o["customer_code"] == "CUS001")
    assert [(line["sku"], line["qty"], line["matched_on"]) for line in ramesh["lines"]] == [
        ("ST-0002", 15, "alias"),
        ("ST-0051", 10, "alias"),
    ]
    assert ramesh["status"] == "awaiting_confirmation" and ramesh["source_lines"] == [2, 4]

    proposals = (await customers.get("/proposals")).json()["items"]
    assert {p["kind"] for p in proposals} == {"confirm_order"}
    om_sai = proposal_for(proposals, "CUS003")
    assert om_sai["subject"] == {"type": "order", "code": "CUS003", "name": "Om Sai Hardware"}
    assert om_sai["numbers"]["ready"] is False
    assert "choose the product for: 'panel'" in om_sai["reason"]
    # 15 x Rs 1,950 (ST-0002) + 10 x Rs 55 (ST-0051), at list prices
    assert proposal_for(proposals, "CUS001")["numbers"]["est_value"] == "29800.00"

    [enquiry] = (await customers.get("/enquiries")).json()["items"]
    assert (enquiry["sender"], enquiry["customer_code"]) == ("A1 Electric Store", "CUS013")


async def test_a_ready_order_is_confirmed_by_approving_it(
    customers: AsyncClient, db_session: AsyncSession
) -> None:
    await upload_chat(customers)
    proposal = proposal_for((await customers.get("/proposals")).json()["items"], "CUS001")

    response = await customers.post(f"/proposals/{proposal['id']}/approve")

    assert response.status_code == 200
    [order] = (await customers.get("/orders", params={"status": "confirmed"})).json()["items"]
    assert order["id"] == proposal["order_id"]
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.action == "proposal.approve"))
    assert audit is not None and audit.after is not None and audit.after["order_id"] == order["id"]


async def test_an_incomplete_order_cant_be_confirmed_until_the_owner_fixes_it(
    customers: AsyncClient,
) -> None:
    await upload_chat(customers)
    proposal = proposal_for((await customers.get("/proposals")).json()["items"], "CUS003")

    refused = await customers.post(f"/proposals/{proposal['id']}/approve")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "order_not_ready"

    order = next(
        o
        for o in (await customers.get("/orders")).json()["items"]
        if o["id"] == proposal["order_id"]
    )
    panel = next(line for line in order["lines"] if line["written"] == "panel")
    fixed = await customers.patch(
        f"/orders/{order['id']}/lines/{panel['id']}", json={"sku": "ST-0021"}
    )
    assert fixed.status_code == 200
    assert (
        next(line for line in fixed.json()["lines"] if line["id"] == panel["id"])["matched_on"]
        == "owner"
    )

    refreshed = proposal_for((await customers.get("/proposals")).json()["items"], "CUS003")
    assert refreshed["numbers"]["ready"] is True
    assert (await customers.post(f"/proposals/{proposal['id']}/approve")).status_code == 200


async def test_a_line_can_be_removed_and_a_rejected_order_is_closed(customers: AsyncClient) -> None:
    await upload_chat(customers)
    proposal = proposal_for((await customers.get("/proposals")).json()["items"], "CUS003")
    order_id = proposal["order_id"]
    order = next(o for o in (await customers.get("/orders")).json()["items"] if o["id"] == order_id)
    panel = next(line for line in order["lines"] if line["written"] == "panel")

    removed = await customers.patch(
        f"/orders/{order_id}/lines/{panel['id']}", json={"remove": True}
    )
    assert [line["written"] for line in removed.json()["lines"]] == ["6a switch"]

    await customers.post(f"/proposals/{proposal['id']}/reject", json={"note": "called, cancelled"})
    [order] = (await customers.get("/orders", params={"status": "rejected"})).json()["items"]
    assert order["id"] == order_id
    late = await customers.patch(
        f"/orders/{order_id}/lines/{order['lines'][0]['id']}", json={"remove": True}
    )
    assert late.status_code == 409


async def test_the_same_chat_cant_be_uploaded_twice(customers: AsyncClient) -> None:
    first = await upload_chat(customers)
    use_model(FakeModel(READINGS))
    again = await customers.post(
        "/uploads/whatsapp", files={"file": ("copy.txt", CHAT, "text/plain")}
    )
    assert again.status_code == 409
    assert again.json()["error"]["details"] == {"upload_id": first["upload"]["id"]}


async def test_running_checks_leaves_order_proposals_alone(customers: AsyncClient) -> None:
    await upload_chat(customers)
    await customers.post("/proposals/run")
    proposals = (await customers.get("/proposals")).json()["items"]
    assert len(proposals) == 2 and {p["status"] for p in proposals} == {"pending"}


async def test_a_thread_the_model_cant_read_is_reported_not_guessed(customers: AsyncClient) -> None:
    readings = [LlmError("unavailable", "Ollama is not running"), READINGS[1], READINGS[2]]
    accepted = await upload_chat(customers, readings)
    issues = (await customers.get("/issues", params={"upload_id": accepted["upload"]["id"]})).json()
    assert "thread_not_read" in {i["issue_type"] for i in issues["items"]}
    assert len((await customers.get("/orders")).json()["items"]) == 1


async def test_an_unexpected_failure_marks_the_upload_failed(customers: AsyncClient) -> None:
    accepted = await upload_chat(customers, [RuntimeError("disk full"), *READINGS[1:]])
    upload = (await customers.get(f"/uploads/{accepted['upload']['id']}")).json()
    assert upload["status"] == "failed" and "disk full" in upload["error"]
    assert (await customers.get("/orders")).json()["items"] == []  # nothing half-saved


async def test_a_file_that_isnt_a_chat_is_refused(customers: AsyncClient) -> None:
    response = await customers.post(
        "/uploads/whatsapp", files={"file": ("notes.txt", b"just some notes", "text/plain")}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_a_chat"


async def test_the_owner_can_correct_a_quantity(
    customers: AsyncClient, db_session: AsyncSession
) -> None:
    await upload_chat(customers)
    proposal = proposal_for((await customers.get("/proposals")).json()["items"], "CUS003")
    order = next(
        o
        for o in (await customers.get("/orders")).json()["items"]
        if o["id"] == proposal["order_id"]
    )
    panel = next(line for line in order["lines"] if line["written"] == "panel")

    fixed = await customers.patch(
        f"/orders/{order['id']}/lines/{panel['id']}", json={"sku": "ST-0021", "qty": 25}
    )

    line = next(line for line in fixed.json()["lines"] if line["id"] == panel["id"])
    assert (line["sku"], line["qty"]) == ("ST-0021", 25)
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.action == "order.line_change"))
    assert audit is not None and audit.before is not None and audit.after is not None
    assert (audit.before["qty"], audit.after["qty"]) == (20, 25)
    nothing = await customers.patch(f"/orders/{order['id']}/lines/{panel['id']}", json={})
    assert nothing.status_code == 422
