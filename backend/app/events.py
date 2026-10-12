"""Live updates: tell the open pages that something changed, so they reload it.

The browser keeps a WebSocket open to /ws (api/ws.py): a connection that stays open, so the
server can send a message whenever it likes instead of waiting to be asked. Each connection
subscribes here and gets its own small queue; publishing puts the event in every queue.

Events carry only what changed (a kind and ids), never the data itself: a page that hears
"proposal 42 was explained" reloads what it shows over normal HTTP, so every check and every
type stays in the API. Publish only after the change is committed, or a page could reload
before the data is there.

One process only (decision 039): events reach the pages connected to this server process,
which is all the demo runs. Several processes would need Postgres LISTEN/NOTIFY (see Ideas).
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

EventType = Literal[
    "proposal.created",  # new proposals: after "Run checks", a WhatsApp chat or an invoice
    "proposal.updated",  # numbers changed (an order line fixed) or replaced by newer data
    "proposal.explained",  # the agent stored the model's (or the template's) explanation
    "proposal.decided",  # approved or rejected
    "upload.finished",  # a background upload (chat, invoice) was processed or failed
]


@dataclass(frozen=True)
class Event:
    type: EventType
    data: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


class Broadcaster:
    """Hands each published event to every subscriber, in this process."""

    def __init__(self, queue_size: int = 100) -> None:
        self._queue_size = queue_size
        self._queues: set[asyncio.Queue[Event]] = set()

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    def publish(self, event: Event) -> None:
        for queue in self._queues:
            if queue.full():
                # A page that stopped reading loses its oldest event, never blocks the app.
                # Any event means "reload", so the newest one is enough.
                queue.get_nowait()
            queue.put_nowait(event)

    @property
    def subscribers(self) -> int:
        return len(self._queues)


broadcaster = Broadcaster()


# One function per event, so every event has one shape (mirrored in frontend/src/lib/live.ts).


def proposals_created(proposal_ids: list[int]) -> None:
    if proposal_ids:
        broadcaster.publish(Event("proposal.created", {"proposal_ids": proposal_ids}))


def proposals_updated(proposal_ids: list[int]) -> None:
    if proposal_ids:
        broadcaster.publish(Event("proposal.updated", {"proposal_ids": proposal_ids}))


def proposal_explained(proposal_id: int) -> None:
    broadcaster.publish(Event("proposal.explained", {"proposal_id": proposal_id}))


def proposal_decided(proposal_id: int, status: str) -> None:
    broadcaster.publish(Event("proposal.decided", {"proposal_id": proposal_id, "status": status}))


def upload_finished(upload_id: int, kind: str, status: str) -> None:
    broadcaster.publish(
        Event("upload.finished", {"upload_id": upload_id, "kind": kind, "status": status})
    )
