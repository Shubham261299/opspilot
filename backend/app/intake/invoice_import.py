"""Save one supplier invoice PDF. Like a WhatsApp chat, it is read in two parts:

1. start_invoice_upload(), in the request: refuse an identical file uploaded before, get the
   PDF's text (a PDF without text is refused at once), save the upload as `processing`.
2. process_invoice_upload(), in the background: the language model reads the text (about a
   minute on a laptop CPU), code checks it (intake/invoices.py), and ONE transaction saves the
   invoice, its lines, its issues and an audit row.
"""

import hashlib
import logging
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import events
from app.db.audit import audit_entry
from app.db.models import SupplierInvoice, SupplierInvoiceLine, Upload
from app.db.queries import SUPPLIER_INVOICE, ReferenceData, load_reference_data
from app.domain.anomalies import invoice_key
from app.intake.errors import AlreadyUploaded, IntakeError, UploadRejected
from app.intake.importing import (
    issue_rows,
    mark_background_upload_failed,
    save_failed_upload,
    severity_counts,
)
from app.intake.invoice_pdf import pdf_text
from app.intake.invoices import InvoiceReading, read_invoice
from app.intake.product_picks import Ask
from app.proposals.invoices import (
    copy_without_original_issue,
    create_invoice_proposal,
    duplicate_issue,
    find_duplicate,
    today_basis,
)

logger = logging.getLogger(__name__)


async def start_invoice_upload(
    session: AsyncSession, *, filename: str, content: bytes, actor: str
) -> tuple[Upload, str]:
    """The upload (status `processing`) and the PDF's text, for the background step."""
    digest = hashlib.sha256(content).hexdigest()
    earlier = await session.scalar(
        select(Upload.id).where(
            Upload.kind == SUPPLIER_INVOICE,
            Upload.content_sha256 == digest,
            Upload.status.in_(("processing", "processed")),
        )
    )
    if earlier is not None:
        raise AlreadyUploaded(earlier, "invoice PDF")
    try:
        text = pdf_text(content)
    except IntakeError as exc:
        upload = await save_failed_upload(
            session, kind=SUPPLIER_INVOICE, filename=filename, error=exc, actor=actor
        )
        raise UploadRejected(exc.code, exc.message, upload.id) from exc
    upload = Upload(
        kind=SUPPLIER_INVOICE, filename=filename, status="processing", content_sha256=digest
    )
    session.add(upload)
    await session.flush()
    session.add(
        audit_entry(
            actor=actor,
            action=f"upload.{SUPPLIER_INVOICE}",
            entity_type="upload",
            entity_id=upload.id,
            after={"filename": filename, "status": "processing"},
        )
    )
    await session.commit()
    return upload, text


async def process_invoice_upload(
    sessions: async_sessionmaker[AsyncSession],
    upload_id: int,
    text: str,
    *,
    ask: Ask,
    today: date,
    actor: str,
) -> None:
    """Runs after the response was sent. Never raises: a failure is recorded on the upload."""
    try:
        async with sessions() as session:  # a short read, closed before the model starts
            reference = await load_reference_data(session)
        reading = await read_invoice(text, reference.catalog, ask, today)
        async with sessions() as session:
            await _save(session, upload_id, reading, reference, today, actor)
    except Exception as exc:
        await mark_background_upload_failed(
            sessions,
            upload_id,
            kind=SUPPLIER_INVOICE,
            what="Reading the invoice",
            error=exc,
            actor=actor,
        )


async def _save(
    session: AsyncSession,
    upload_id: int,
    reading: InvoiceReading,
    reference: ReferenceData,
    today: date,
    actor: str,
) -> None:
    upload = await session.get(Upload, upload_id)
    if upload is None:
        return
    product_ids, supplier_ids = reference.product_ids, reference.supplier_ids
    invoice = SupplierInvoice(
        upload_id=upload_id,
        supplier_id=supplier_ids.get(reading.supplier_code or ""),
        supplier_name=reading.supplier_name,
        supplier_gstin=reading.supplier_gstin,
        invoice_no=reading.invoice_no,
        invoice_date=reading.invoice_date,
        subtotal=reading.subtotal,
        gst_amount=reading.gst_amount,
        grand_total=reading.grand_total,
        marked_duplicate=reading.marked_duplicate,
        notes=reading.notes,
        lines_read_by=reading.lines_read_by,
    )
    session.add(invoice)
    await session.flush()
    session.add_all(
        SupplierInvoiceLine(
            invoice_id=invoice.id,
            line_no=line.number,
            product_id=product_ids.get(line.sku or ""),
            description=line.description,
            qty=line.qty,
            rate=line.rate,
            amount=line.amount,
            matched_on=line.matched_on,
        )
        for line in reading.lines
    )
    await session.flush()
    # Policy 4.2: the same supplier's invoice number again is a duplicate and is never paid.
    # Two copies can be read at the same time; this lock (held until commit) makes the second
    # wait for the first, so it sees it and can't also become payable.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"invoice:{invoice.supplier_id}:{invoice_key(invoice.invoice_no)}"},
    )
    original = await find_duplicate(session, invoice)
    if original is not None:
        invoice.status = "duplicate"
        reading.issues.append(duplicate_issue(invoice, original))
    elif invoice.marked_duplicate:
        reading.issues.append(copy_without_original_issue(invoice))
    session.add_all(issue_rows(upload_id, upload.filename, reading.issues, product_ids=product_ids))
    await session.flush()  # the proposal reads the arithmetic issues
    proposal_ids = []
    if original is None:
        proposal = await create_invoice_proposal(session, invoice, today_basis(today, upload_id))
        await session.flush()
        proposal_ids.append(proposal.id)
    upload.status = "processed"
    upload.as_of = reading.invoice_date
    upload.rows_read = len(reading.lines)
    upload.rows_loaded = 1
    session.add(
        audit_entry(
            actor=actor,
            action=f"upload.{SUPPLIER_INVOICE}",
            entity_type="upload",
            entity_id=upload_id,
            before={"status": "processing"},
            after={
                "status": "processed",
                "invoice_id": invoice.id,
                "supplier": reading.supplier_code,
                "invoice_no": reading.invoice_no,
                "grand_total": str(reading.grand_total),
                "lines_read_by": reading.lines_read_by,
                "duplicate_of": original.invoice_id if original else None,
                "issues": severity_counts(reading.issues),
            },
        )
    )
    await session.commit()
    events.proposals_created(proposal_ids)
    events.upload_finished(upload_id, SUPPLIER_INVOICE, "processed")
    logger.info(
        "supplier invoice processed", extra={"upload_id": upload_id, "invoice_id": invoice.id}
    )
