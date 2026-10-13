"""Save the company policy: one snapshot of numbered rules, each with its embedding.

Uploading the policy again replaces every rule in one transaction (like the dues sheet). The same
file is accepted again on purpose: that is how the rules are re-embedded after the embedding
model is changed. Nothing is replaced unless the whole file was read and embedded.
"""

import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.db.audit import audit_entry
from app.db.models import PolicyRule, Upload
from app.db.queries import COMPANY_POLICY
from app.intake.errors import IntakeError, UploadRejected
from app.intake.importing import issue_rows, save_failed_upload, severity_counts
from app.intake.issues import IssueRecord
from app.intake.policy import PolicyReading, embedding_text, read_policy_pdf
from app.llm.client import LlmError
from app.llm.embeddings import Embedded, Embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicyImport:
    upload: Upload
    issues: list[IssueRecord]
    rules_loaded: int
    embedding_model: str


async def import_policy(
    session: AsyncSession, *, filename: str, content: bytes, embed: Embedder, actor: str
) -> PolicyImport:
    try:
        reading = read_policy_pdf(content)
        embedded = await _embed_rules(reading, embed)
    except IntakeError as exc:
        upload = await save_failed_upload(
            session, kind=COMPANY_POLICY, filename=filename, error=exc, actor=actor
        )
        raise UploadRejected(exc.code, exc.message, upload.id) from exc

    upload = Upload(
        kind=COMPANY_POLICY,
        filename=filename,
        status="processed",
        rows_read=len(reading.rules),
        rows_loaded=len(reading.rules),
        content_sha256=hashlib.sha256(content).hexdigest(),
    )
    session.add(upload)
    await session.flush()
    before = await _current_rules(session)
    await session.execute(delete(PolicyRule))
    session.add_all(
        PolicyRule(
            code=rule.code,
            section_no=rule.section_no,
            section_title=rule.section_title,
            text=rule.text,
            embedding=vector,
            embedding_model=embedded.model,
            upload_id=upload.id,
        )
        for rule, vector in zip(reading.rules, embedded.vectors, strict=True)
    )
    session.add_all(issue_rows(upload.id, filename, reading.issues))
    session.add(
        audit_entry(
            actor=actor,
            action=f"upload.{COMPANY_POLICY}",
            entity_type="upload",
            entity_id=upload.id,
            before=before,
            after={
                "filename": filename,
                "version": reading.version,
                "rules": [rule.code for rule in reading.rules],
                "embedding_model": embedded.model,
                "issues": severity_counts(reading.issues),
            },
        )
    )
    await session.commit()
    events.upload_finished(upload.id, COMPANY_POLICY, "processed")
    logger.info(
        "policy imported",
        extra={"upload_id": upload.id, "rules": len(reading.rules), "model": embedded.model},
    )
    return PolicyImport(upload, reading.issues, len(reading.rules), embedded.model)


async def _embed_rules(reading: PolicyReading, embed: Embedder) -> Embedded:
    try:
        return await embed([embedding_text(rule) for rule in reading.rules], "document")
    except LlmError as exc:
        raise IntakeError(
            "embedding_failed",
            f"The rules were read, but they couldn't be embedded: {exc.message} "
            "The policy already stored was left as it was.",
        ) from exc


async def _current_rules(session: AsyncSession) -> dict[str, object]:
    """What is replaced, for the audit row."""
    count = await session.scalar(select(func.count()).select_from(PolicyRule))
    model = await session.scalar(select(PolicyRule.embedding_model).limit(1))
    return {"rules": count, "embedding_model": model}
