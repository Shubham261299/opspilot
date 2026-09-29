"""Save one stock register upload. This is the only intake module that uses the database.

Everything is written in ONE transaction: the upload row, the clean stock counts, open PO
notes, every issue and an audit_log row. Either all of it is saved or none of it. A file
that can't be read at all is still recorded, as a 'failed' upload with its own audit row.
"""

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import audit_entry
from app.db.models import Issue, OpenPoNote, StockLevel, Upload
from app.db.queries import STOCK_REGISTER, load_reference_data
from app.intake.errors import IntakeError, UploadRejected
from app.intake.stock_register import StockRegisterResult, parse_stock_register

logger = logging.getLogger(__name__)
AUDIT_ACTION = "upload.stock_register"


@dataclass(frozen=True)
class StockImport:
    upload: Upload
    result: StockRegisterResult


async def import_stock_register(
    session: AsyncSession, *, filename: str, content: bytes, today: date, actor: str
) -> StockImport:
    reference = await load_reference_data(session)
    try:
        # pandas work is CPU-heavy; a worker thread keeps the server free for other requests.
        result = await asyncio.to_thread(parse_stock_register, content, reference.catalog, today)
    except IntakeError as exc:
        upload = await _save_failed_upload(session, filename, exc, actor)
        raise UploadRejected(exc.code, exc.message, upload.id) from exc

    upload = Upload(
        kind=STOCK_REGISTER,
        filename=filename,
        status="processed",
        as_of=result.as_of,
        rows_read=result.rows_read,
        rows_loaded=len(result.stock_rows),
    )
    session.add(upload)
    await session.flush()  # sends the INSERT so upload.id is known; still one transaction

    product_ids = reference.product_ids
    session.add_all(
        StockLevel(
            upload_id=upload.id,
            product_id=product_ids[row.sku],
            qty_on_hand=row.qty_on_hand,
            as_of=result.as_of,
            source_row=row.source_row,
            remarks=row.remarks,
        )
        for row in result.stock_rows
    )
    session.add_all(
        OpenPoNote(
            upload_id=upload.id,
            product_id=product_ids[note.sku],
            supplier_id=reference.supplier_ids.get(note.supplier_code or ""),
            qty=note.qty,
            ordered_on=note.ordered_on,
            note=note.note,
            source_row=note.source_row,
        )
        for note in result.po_notes
    )
    session.add_all(
        Issue(
            upload_id=upload.id,
            product_id=product_ids.get(issue.sku or ""),
            source_file=filename,
            source_row=issue.source_row,
            issue_type=issue.issue_type.value,
            severity=issue.severity,
            detail=issue.detail,
            raw=issue.raw,
        )
        for issue in result.issues
    )
    summary = summarise(upload, result)
    session.add(
        audit_entry(
            actor=actor,
            action=AUDIT_ACTION,
            entity_type="upload",
            entity_id=upload.id,
            after=summary,
        )
    )
    await session.commit()
    logger.info(
        "stock register processed",
        extra={  # not "filename": logging reserves that name for the source file
            "upload_id": upload.id,
            "rows_read": result.rows_read,
            "rows_loaded": len(result.stock_rows),
            "issues": summary["issues"],
        },
    )
    return StockImport(upload=upload, result=result)


def summarise(upload: Upload, result: StockRegisterResult) -> dict[str, object]:
    """The numbers that describe one processed upload (used in the audit row and logs)."""
    return {
        "filename": upload.filename,
        "status": upload.status,
        "as_of": result.as_of.isoformat(),
        "rows_read": result.rows_read,
        "rows_loaded": len(result.stock_rows),
        "po_notes": len(result.po_notes),
        "issues": dict(Counter(issue.severity for issue in result.issues)),
    }


async def _save_failed_upload(
    session: AsyncSession, filename: str, error: IntakeError, actor: str
) -> Upload:
    upload = Upload(kind=STOCK_REGISTER, filename=filename, status="failed", error=error.message)
    session.add(upload)
    await session.flush()
    session.add(
        audit_entry(
            actor=actor,
            action=AUDIT_ACTION,
            entity_type="upload",
            entity_id=upload.id,
            after={"filename": filename, "status": "failed", "error": error.code},
        )
    )
    await session.commit()
    logger.warning(
        "stock register rejected", extra={"upload_id": upload.id, "error_code": error.code}
    )
    return upload
