"""Live events: each change that the open pages show is announced after it is committed."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app import events
from app.events import Event
from app.llm.client import LlmError
from tests.integration.test_anomaly_flow import history, royal_order, upload_invoice
from tests.integration.test_api_proposals import loaded, pending, run

__all__ = ["history", "loaded"]  # fixtures, imported so pytest finds them here


@pytest.fixture
def heard() -> Iterator[asyncio.Queue[Event]]:
    """What a page connected to /ws would receive."""
    with events.broadcaster.subscribe() as queue:
        yield queue


def drain(queue: asyncio.Queue[Event]) -> list[dict[str, Any]]:
    found = []
    while not queue.empty():
        found.append(queue.get_nowait().as_json())
    return found


def of_type(found: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [event for event in found if event["type"] == event_type]


async def test_checks_explanations_and_decisions_are_announced(
    loaded: AsyncClient, heard: asyncio.Queue[Event]
) -> None:
    await run(loaded)  # the agents explain each new proposal in the background

    found = drain(heard)
    ids = sorted(p["id"] for p in await pending(loaded))
    [created] = of_type(found, "proposal.created")
    assert sorted(created["proposal_ids"]) == ids
    # Every new proposal's explanation is announced once it is stored (the template here).
    assert sorted(e["proposal_id"] for e in of_type(found, "proposal.explained")) == ids

    await loaded.post(f"/proposals/{ids[0]}/reject", json={"note": "not now"})

    assert drain(heard) == [
        {"type": "proposal.decided", "proposal_id": ids[0], "status": "rejected"}
    ]


@pytest.mark.usefixtures("seeded")
async def test_a_read_invoice_is_announced_with_its_proposal(
    client: AsyncClient, sample_data_dir: Path, heard: asyncio.Queue[Event]
) -> None:
    upload_id = await upload_invoice(client, sample_data_dir / "invoice_brightline_BL-0874.pdf")

    found = drain(heard)
    [proposal] = await pending(client)
    assert of_type(found, "proposal.created") == [
        {"type": "proposal.created", "proposal_ids": [proposal["id"]]}
    ]
    assert of_type(found, "upload.finished") == [
        {
            "type": "upload.finished",
            "upload_id": upload_id,
            "kind": "supplier_invoice",
            "status": "processed",
        }
    ]


class ModelDown:
    async def __call__(self, messages: Any, schema: Any, purpose: str) -> Any:
        raise LlmError("unavailable", "The language model could not be reached.")


@pytest.mark.usefixtures("seeded")
async def test_a_failed_upload_is_announced(
    client: AsyncClient, sample_data_dir: Path, heard: asyncio.Queue[Event]
) -> None:
    path = sample_data_dir / "invoice_kiran_cables_KC-2291.pdf"
    upload_id = await upload_invoice(client, path, ModelDown())

    assert drain(heard) == [
        {
            "type": "upload.finished",
            "upload_id": upload_id,
            "kind": "supplier_invoice",
            "status": "failed",
        }
    ]


async def test_fixing_an_order_line_is_announced(
    history: AsyncClient, heard: asyncio.Queue[Event]
) -> None:
    proposal = await royal_order(history)
    drain(heard)
    line_id = proposal["numbers"]["lines"][0]["line_id"]

    response = await history.patch(
        f"/orders/{proposal['order_id']}/lines/{line_id}", json={"qty": 20}
    )

    assert response.status_code == 200
    assert drain(heard) == [{"type": "proposal.updated", "proposal_ids": [proposal["id"]]}]
