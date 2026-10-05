"""Save one outstanding-dues upload, in one transaction.

A dues file is a full list of unpaid bills on the day it's uploaded, so each upload is a
snapshot (like a stock count); the latest one is "current". `as_of` is the upload date.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import audit_entry
from app.db.models import CustomerBill, Upload
from app.db.queries import OUTSTANDING_DUES, all_customers
from app.intake.errors import IntakeError, UploadRejected
from app.intake.importing import issue_rows, save_failed_upload, severity_counts
from app.intake.outstanding_dues import DuesResult, parse_outstanding_dues

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuesImport:
    upload: Upload
    result: DuesResult


async def import_outstanding_dues(
    session: AsyncSession, *, filename: str, content: bytes, today: date, actor: str
) -> DuesImport:
    customers = await all_customers(session)
    names = {c.code: c.shop_name for c in customers}
    try:
        result = await asyncio.to_thread(parse_outstanding_dues, content, names, today)
    except IntakeError as exc:
        upload = await save_failed_upload(
            session, kind=OUTSTANDING_DUES, filename=filename, error=exc, actor=actor
        )
        raise UploadRejected(exc.code, exc.message, upload.id) from exc

    upload = Upload(
        kind=OUTSTANDING_DUES,
        filename=filename,
        status="processed",
        as_of=today,
        rows_read=result.rows_read,
        rows_loaded=len(result.bills),
    )
    session.add(upload)
    await session.flush()

    customer_ids = {c.code: c.id for c in customers}
    session.add_all(
        CustomerBill(
            upload_id=upload.id,
            customer_id=customer_ids[bill.customer_code],
            bill_no=bill.bill_no,
            bill_date=bill.bill_date,
            amount=bill.amount,
            received=bill.received,
            balance=bill.balance,
            source_row=bill.source_row,
        )
        for bill in result.bills
    )
    session.add_all(issue_rows(upload.id, filename, result.issues, customer_ids=customer_ids))
    total = sum((bill.balance for bill in result.bills), start=0)
    session.add(
        audit_entry(
            actor=actor,
            action=f"upload.{OUTSTANDING_DUES}",
            entity_type="upload",
            entity_id=upload.id,
            after={
                "filename": filename,
                "status": upload.status,
                "rows_read": result.rows_read,
                "bills_loaded": len(result.bills),
                "total_balance": str(total),
                "issues": severity_counts(result.issues),
            },
        )
    )
    await session.commit()
    logger.info(
        "outstanding dues processed", extra={"upload_id": upload.id, "bills": len(result.bills)}
    )
    return DuesImport(upload, result)
