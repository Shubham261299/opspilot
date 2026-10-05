"""Pieces shared by every importer: issue rows, failed uploads and summaries."""

import logging
from collections import Counter
from collections.abc import Iterable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

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
