"""Save one customers upload, in one transaction.

Customers are master data: a row whose code already exists updates that customer's details
(name, phone, area, credit terms); a new code adds a customer. `on_hold` is never touched
here; only an approved proposal changes it. What changed is written to the audit row.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import audit_entry
from app.db.models import Customer, Upload
from app.db.queries import CUSTOMERS
from app.intake.customers import CustomerRow, CustomersResult, parse_customers
from app.intake.errors import IntakeError, UploadRejected
from app.intake.importing import issue_rows, save_failed_upload, severity_counts

logger = logging.getLogger(__name__)
_FIELDS = ("shop_name", "contact_person", "phone", "area", "credit_limit", "credit_days")


@dataclass(frozen=True)
class CustomersImport:
    upload: Upload
    result: CustomersResult
    added: list[str]
    updated: list[str]


async def import_customers(
    session: AsyncSession, *, filename: str, content: bytes, actor: str
) -> CustomersImport:
    try:
        result = await asyncio.to_thread(parse_customers, content)
    except IntakeError as exc:
        upload = await save_failed_upload(
            session, kind=CUSTOMERS, filename=filename, error=exc, actor=actor
        )
        raise UploadRejected(exc.code, exc.message, upload.id) from exc

    upload = Upload(
        kind=CUSTOMERS,
        filename=filename,
        status="processed",
        rows_read=result.rows_read,
        rows_loaded=len(result.customers),
    )
    session.add(upload)

    existing = {c.code: c for c in (await session.scalars(select(Customer))).all()}
    added: list[str] = []
    changes: dict[str, dict[str, list[Any]]] = {}
    for row in result.customers:
        customer = existing.get(row.code)
        if customer is None:
            customer = Customer(code=row.code, **_values(row))
            session.add(customer)
            existing[row.code] = customer
            added.append(row.code)
            continue
        changed = {
            field: [_json(getattr(customer, field)), _json(new)]
            for field, new in _values(row).items()
            if getattr(customer, field) != new
        }
        if changed:
            for field in changed:
                setattr(customer, field, getattr(row, field))
            changes[row.code] = changed
    await session.flush()  # new customers and the upload get their ids

    customer_ids = {code: customer.id for code, customer in existing.items()}
    session.add_all(issue_rows(upload.id, filename, result.issues, customer_ids=customer_ids))
    summary = {
        "filename": filename,
        "status": upload.status,
        "rows_read": result.rows_read,
        "rows_loaded": len(result.customers),
        "added": added,
        "updated": changes,  # code -> field -> [before, after]
        "issues": severity_counts(result.issues),
    }
    session.add(
        audit_entry(
            actor=actor,
            action=f"upload.{CUSTOMERS}",
            entity_type="upload",
            entity_id=upload.id,
            after=summary,
        )
    )
    await session.commit()
    logger.info(
        "customers processed",
        extra={"upload_id": upload.id, "added": len(added), "updated": len(changes)},
    )
    return CustomersImport(upload, result, added, sorted(changes))


def _values(row: CustomerRow) -> dict[str, Any]:
    return {field: getattr(row, field) for field in _FIELDS}


def _json(value: Any) -> Any:
    return value if value is None or isinstance(value, int | str) else str(value)
