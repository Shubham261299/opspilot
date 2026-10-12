"""Pieces shared by every importer: issue rows, failed uploads and summaries."""

import logging
from collections import Counter
from collections.abc import Iterable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import events
from app.db.audit import audit_entry
from app.db.models import Issue, Upload
from app.intake.errors import IntakeError
from app.intake.issues import IssueRecord

logger = logging.getLogger(__name__)


def issue_rows(
    upload_id: int,
    filename: str,
    issues: Iterable[IssueRecord],
    product_ids: Mapping[str, int] | None = None,
    customer_ids: Mapping[str, int] | None = None,
) -> list[Issue]:
    """IssueRecords from a parser as database rows, linked to their product or customer."""
    product_ids = product_ids or {}
    customer_ids = customer_ids or {}
    return [
        Issue(
            upload_id=upload_id,
            product_id=product_ids.get(issue.sku or ""),
            customer_id=customer_ids.get(issue.customer_code or ""),
            source_file=filename,
            source_row=issue.source_row,
            issue_type=issue.issue_type.value,
            severity=issue.severity,
            detail=issue.detail,
            raw=issue.raw,
        )
        for issue in issues
    ]


def severity_counts(issues: Iterable[IssueRecord]) -> dict[str, int]:
    return dict(Counter(issue.severity for issue in issues))


async def save_failed_upload(
    session: AsyncSession, *, kind: str, filename: str, error: IntakeError, actor: str
) -> Upload:
    """Record a file that couldn't be processed, with its own audit row, and nothing else."""
    upload = Upload(kind=kind, filename=filename, status="failed", error=error.message)
    session.add(upload)
    await session.flush()
    session.add(
        audit_entry(
            actor=actor,
            action=f"upload.{kind}",
            entity_type="upload",
            entity_id=upload.id,
            after={"filename": filename, "status": "failed", "error": error.code},
        )
    )
    await session.commit()
    logger.warning(
        "upload rejected",
        extra={"upload_id": upload.id, "kind": kind, "error_code": error.code},
    )
    return upload


async def mark_background_upload_failed(
    sessions: async_sessionmaker[AsyncSession],
    upload_id: int,
    *,
    kind: str,
    what: str,
    error: Exception,
    actor: str,
) -> None:
    """A background step failed: record why on the upload, with an audit row, instead of
    leaving it `processing`. Nothing else was saved (each import commits once, at the end)."""
    logger.error(
        "background upload failed",
        extra={"upload_id": upload_id, "kind": kind, "error_type": type(error).__name__},
        exc_info=error,
    )
    message = error.message if isinstance(error, IntakeError) else str(error)
    async with sessions() as session:
        upload = await session.get(Upload, upload_id)
        if upload is None:
            return
        upload.status = "failed"
        upload.error = f"{what} failed: {message}"[:500]
        session.add(
            audit_entry(
                actor=actor,
                action=f"upload.{kind}",
                entity_type="upload",
                entity_id=upload_id,
                after={"status": "failed", "error": type(error).__name__},
            )
        )
        await session.commit()
    events.upload_finished(upload_id, kind, "failed")
