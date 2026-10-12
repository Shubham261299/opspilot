"""The live-update broadcaster and the /ws WebSocket (no database needed)."""

import asyncio

from fastapi import FastAPI
from starlette.testclient import TestClient

from app import events
from app.api import ws
from app.events import Broadcaster, Event


def drain(queue: asyncio.Queue[Event]) -> list[dict[str, object]]:
    found = []
    while not queue.empty():
        found.append(queue.get_nowait().as_json())
    return found


def test_every_subscriber_gets_every_event() -> None:
    hub = Broadcaster()
    with hub.subscribe() as first, hub.subscribe() as second:
        hub.publish(Event("proposal.explained", {"proposal_id": 7}))
        expected = [{"type": "proposal.explained", "proposal_id": 7}]
        assert drain(first) == drain(second) == expected


def test_a_closed_subscription_gets_nothing_more() -> None:
    hub = Broadcaster()
    with hub.subscribe() as queue:
        assert hub.subscribers == 1
    hub.publish(Event("proposal.explained", {"proposal_id": 7}))
    assert hub.subscribers == 0 and queue.empty()


def test_a_page_that_stops_reading_keeps_only_the_newest_events() -> None:
    hub = Broadcaster(queue_size=2)
    with hub.subscribe() as queue:
        for proposal_id in (1, 2, 3):
            hub.publish(Event("proposal.explained", {"proposal_id": proposal_id}))
        assert [e["proposal_id"] for e in drain(queue)] == [2, 3]


def test_nothing_is_published_for_an_empty_list() -> None:
    with events.broadcaster.subscribe() as queue:
        events.proposals_created([])
        events.proposals_updated([])
        events.proposals_created([4, 5])
        assert drain(queue) == [{"type": "proposal.created", "proposal_ids": [4, 5]}]


def test_the_websocket_says_hello_then_forwards_events() -> None:
    app = FastAPI()  # only the WebSocket route: no database, no agents
    app.include_router(ws.router)
    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        assert websocket.receive_json() == {"type": "hello"}  # subscribed from here on
        assert events.broadcaster.subscribers == 1
        # Publish on the server's own event loop, as the app does.
        websocket.portal.call(events.upload_finished, 3, "supplier_invoice", "processed")
        assert websocket.receive_json() == {
            "type": "upload.finished",
            "upload_id": 3,
            "kind": "supplier_invoice",
            "status": "processed",
        }
        websocket.close()  # the page goes away
        websocket.portal.call(_until_unsubscribed)


async def _until_unsubscribed() -> None:
    async with asyncio.timeout(2):
        while events.broadcaster.subscribers:
            await asyncio.sleep(0.01)
