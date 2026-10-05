"""Save one sales-history upload, in one transaction.

The export covers the last 90 days in full, so each upload is a snapshot and the latest one
is "current" (as_of = the last sale date in it). ~8,000 lines are written with one bulk
INSERT instead of one statement per line.
"""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import audit_entry
from app.db.models import Customer, SalesLine, Upload
from app.db.queries import SALES_HISTORY, load_reference_data
from app.intake.errors import IntakeError, UploadRejected
from app.intake.importing import issue_rows, save_failed_upload, severity_counts
from app.intake.sales_history import SalesResult, parse_sales_history

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SalesImport:
    upload: Upload
    result: SalesResult


async def import_sales_history(
    session: AsyncSession, *, filename: str, content: bytes, actor: str
) -> SalesImport:
    reference = await load_reference_data(session)
    customer_ids = {
        code: id_ for code, id_ in (await session.execute(select(Customer.code, Customer.id)))
    }
    try:
        result = await asyncio.to_thread(
            parse_sales_history, content, customer_ids.keys(), reference.product_ids.keys()
        )
    except IntakeError as exc:
        upload = await save_failed_upload(
            session, kind=SALES_HISTORY, filename=filename, error=exc, actor=actor
        )
        raise UploadRejected(exc.code, exc.message, upload.id) from exc

    upload = Upload(
        kind=SALES_HISTORY,
        filename=filename,
        status="processed",
        as_of=result.last_sale,
        rows_read=result.rows_read,
        rows_loaded=len(result.sales),
    )
    session.add(upload)
    await session.flush()

    if result.sales:
        # A list of dicts with insert() is sent as a few large multi-row INSERTs.
        await session.execute(
            insert(SalesLine),
            [
                {
                    "upload_id": upload.id,
                    "sale_date": sale.sale_date,
                    "customer_id": customer_ids[sale.customer_code],
                    "product_id": reference.product_ids[sale.sku],
                    "qty": sale.qty,
                    "unit_price": sale.unit_price,
                    "amount": sale.amount,
                }
                for sale in result.sales
            ],
        )
    session.add_all(
        issue_rows(
            upload.id,
            filename,
            result.issues,
            product_ids=reference.product_ids,
            customer_ids=customer_ids,
        )
    )
    session.add(
        audit_entry(
            actor=actor,
            action=f"upload.{SALES_HISTORY}",
            entity_type="upload",
            entity_id=upload.id,
            after={
                "filename": filename,
                "status": upload.status,
                "rows_read": result.rows_read,
                "rows_loaded": len(result.sales),
                "last_sale": result.last_sale.isoformat() if result.last_sale else None,
                "issues": severity_counts(result.issues),
            },
        )
    )
    await session.commit()
    logger.info(
        "sales history processed", extra={"upload_id": upload.id, "lines": len(result.sales)}
    )
    return SalesImport(upload, result)
