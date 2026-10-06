"""Save one WhatsApp chat upload. Reading it takes minutes (one model call per customer
thread on a laptop CPU), so it happens in two parts:

1. start_whatsapp_upload(), inside the request: check the file, refuse an identical file
   that was already uploaded, split it into messages, and save the upload as `processing`.
   The API answers 202 Accepted straight away.
2. process_whatsapp_upload(), in the background: the model reads every thread (no database
   connection is held meanwhile), then ONE transaction saves the orders, their "confirm
   order" proposals, enquiries, issues and the audit row, and marks the upload `processed`.
   If anything fails, the upload is marked `failed` with the reason; nothing half-saved.
"""

import hashlib
import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.audit import audit_entry
from app.db.models import CustomerOrder, CustomerOrderLine, Enquiry, Upload
from app.db.queries import WHATSAPP_CHAT, all_customers, load_reference_data
from app.intake.errors import IntakeError, UploadRejected
from app.intake.importing import issue_rows, save_failed_upload, severity_counts
from app.intake.whatsapp import ChatFormatError, parse_chat
from app.intake.whatsapp_orders import Ask, OrdersReading, read_whatsapp_orders
from app.proposals.orders import create_order_proposal

logger = logging.getLogger(__name__)
ACTION = f"upload.{WHATSAPP_CHAT}"


class AlreadyUploaded(IntakeError):
    def __init__(self, upload_id: int) -> None:
        super().__init__(
            "already_uploaded",
            f"This exact chat was already uploaded as upload #{upload_id}; its orders are "
            "in the Approval Inbox.",
        )
        self.upload_id = upload_id


async def start_whatsapp_upload(
    session: AsyncSession, *, filename: str, content: bytes, shop_name: str, actor: str
) -> Upload:
    digest = hashlib.sha256(content).hexdigest()
    earlier = await session.scalar(
        select(Upload.id).where(
            Upload.kind == WHATSAPP_CHAT,
            Upload.content_sha256 == digest,
            Upload.status.in_(("processing", "processed")),
        )
    )
    if earlier is not None:
        raise AlreadyUploaded(earlier)
    try:
        chat = parse_chat(_text(content), shop_name)
    except (IntakeError, ChatFormatError) as exc:
        error = exc if isinstance(exc, IntakeError) else IntakeError("not_a_chat", str(exc))
        upload = await save_failed_upload(
            session, kind=WHATSAPP_CHAT, filename=filename, error=error, actor=actor
        )
        raise UploadRejected(error.code, error.message, upload.id) from exc

    upload = Upload(
        kind=WHATSAPP_CHAT,
        filename=filename,
        status="processing",
        as_of=chat.messages[-1].sent_at.date(),
        rows_read=len(chat.messages),
        content_sha256=digest,
    )
    session.add(upload)
    await session.flush()
    session.add(
        audit_entry(
            actor=actor,
            action=ACTION,
            entity_type="upload",
            entity_id=upload.id,
            after={"filename": filename, "status": "processing", "messages": len(chat.messages)},
        )
    )
    await session.commit()
    return upload


async def process_whatsapp_upload(
    sessions: async_sessionmaker[AsyncSession],
    upload_id: int,
    content: bytes,
    *,
    ask: Ask,
    shop_name: str,
    today: date,
    actor: str,
) -> None:
    """Runs after the response was sent. Never raises: a failure is recorded on the upload."""
    try:
        async with sessions() as session:  # a short read, closed before the model starts
            reference = await load_reference_data(session)
            customers = {c.code: c.shop_name for c in await all_customers(session)}
        chat = parse_chat(_text(content), shop_name)
        reading = await read_whatsapp_orders(chat, reference.catalog, customers, ask)
        async with sessions() as session:
            await _save(session, upload_id, reading, reference.product_ids, today, actor)
    except Exception as exc:  # anything at all: record it rather than leave "processing"
        logger.exception("whatsapp upload failed", extra={"upload_id": upload_id})
        async with sessions() as session:
            upload = await session.get(Upload, upload_id)
            if upload is not None:
                upload.status = "failed"
                upload.error = f"Reading the chat failed: {exc}"[:500]
                session.add(
                    audit_entry(
                        actor=actor,
                        action=ACTION,
                        entity_type="upload",
                        entity_id=upload_id,
                        after={"status": "failed", "error": type(exc).__name__},
                    )
                )
                await session.commit()


async def _save(
    session: AsyncSession,
    upload_id: int,
    reading: OrdersReading,
    product_ids: dict[str, int],
    today: date,
    actor: str,
) -> None:
    upload = await session.get(Upload, upload_id)
    if upload is None:
        return  # deleted meanwhile
    customer_ids = {c.code: c.id for c in await all_customers(session)}
    basis: dict[str, Any] = {"today": today.isoformat(), "whatsapp_upload_id": upload_id}
    proposals = []
    for parsed in reading.orders:
        order = CustomerOrder(
            upload_id=upload_id,
            customer_id=customer_ids.get(parsed.customer_code or ""),
            sender=parsed.sender,
            first_sent_at=parsed.first_sent_at,
            source_lines=list(parsed.source_lines),
            unclear=list(parsed.unclear),
        )
        session.add(order)
        await session.flush()
        session.add_all(
            CustomerOrderLine(
                order_id=order.id,
                product_id=product_ids.get(line.sku or ""),
                written=line.written,
                qty=line.qty,
                unit_written=line.unit_written,
                matched_on=line.matched_on,
            )
            for line in parsed.lines
        )
        await session.flush()
        proposals.append(await create_order_proposal(session, order, basis))
    session.add_all(
        Enquiry(
            upload_id=upload_id,
            customer_id=customer_ids.get(e.customer_code or ""),
            sender=e.sender,
            text=e.text,
            source_line=e.source_line,
        )
        for e in reading.enquiries
    )
    session.add_all(
        issue_rows(
            upload_id,
            upload.filename,
            reading.issues,
            product_ids=product_ids,
            customer_ids=customer_ids,
        )
    )
    upload.status = "processed"
    upload.rows_loaded = len(reading.orders)
    session.add(
        audit_entry(
            actor=actor,
            action=ACTION,
            entity_type="upload",
            entity_id=upload_id,
            before={"status": "processing"},
            after={
                "status": "processed",
                "orders": len(reading.orders),
                "enquiries": len(reading.enquiries),
                "no_order": reading.no_order,
                "model_calls": reading.model_calls,
                "seconds": round(reading.seconds),
                "issues": severity_counts(reading.issues),
            },
        )
    )
    await session.commit()
    logger.info(
        "whatsapp upload processed",
        extra={"upload_id": upload_id, "orders": len(reading.orders), "proposals": len(proposals)},
    )


async def fail_interrupted_uploads() -> int:
    """At start-up: uploads still `processing` were cut off by a restart; mark them failed."""
    from app.db.session import get_sessionmaker  # here, so importing this module stays cheap

    async with get_sessionmaker()() as session:
        stuck = (await session.scalars(select(Upload).where(Upload.status == "processing"))).all()
        for upload in stuck:
            upload.status = "failed"
            upload.error = "The server restarted while this chat was being read. Upload it again."
        await session.commit()
    if stuck:
        logger.warning("interrupted uploads marked failed", extra={"uploads": len(stuck)})
    return len(stuck)


def _text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IntakeError("unreadable_file", "The chat export must be a UTF-8 text file.") from exc
