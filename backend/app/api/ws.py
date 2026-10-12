"""GET /ws: a WebSocket that sends live events to the page (see app/events.py)."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events import Event, broadcaster

router = APIRouter(tags=["live"])
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def live_events(websocket: WebSocket) -> None:
    """Sends `{"type": "hello"}` once subscribed, then one JSON message per event, for as
    long as the page keeps the connection open."""
    await websocket.accept()
    with broadcaster.subscribe() as queue:
        await websocket.send_json({"type": "hello"})
        logger.info("live page connected", extra={"listeners": broadcaster.subscribers})
        # Two jobs at once: forward events, and notice the page closing (which may come
        # while no event is due). Whichever ends first ends the other.
        jobs = {
            asyncio.create_task(_forward(queue, websocket)),
            asyncio.create_task(_until_closed(websocket)),
        }
        done, pending = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
        for job in pending:
            job.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for job in done:
            job.result()  # re-raises anything other than the page going away
    logger.info("live page left", extra={"listeners": broadcaster.subscribers})


async def _forward(queue: asyncio.Queue[Event], websocket: WebSocket) -> None:
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.as_json())
    except WebSocketDisconnect:
        return


async def _until_closed(websocket: WebSocket) -> None:
    try:
        while True:
            await websocket.receive_text()  # the page sends nothing; this waits for the close
    except WebSocketDisconnect:
        return
