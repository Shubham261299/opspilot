from decimal import Decimal
from typing import Any, Literal, cast

from fastapi import APIRouter

from app.api.deps import SessionDep
from app.api.schemas import InvoiceLineOut, InvoiceOut, InvoicesOut
from app.db.queries import list_invoices

router = APIRouter(tags=["invoices"])
InvoiceStatus = Literal["awaiting_approval", "approved_for_payment", "rejected", "duplicate"]


@router.get("/invoices")
async def get_invoices(session: SessionDep) -> InvoicesOut:
    """Supplier invoices read from PDFs, newest first. Each line has our cost price and the
    price check from its proposal (the same figures the owner approves on)."""
    items = []
    for view in await list_invoices(session):
        invoice = view.invoice
        numbers = view.proposal.numbers if view.proposal else {}
        checked = {line["line_no"]: line for line in numbers.get("lines", [])}
        items.append(
            InvoiceOut(
                id=invoice.id,
                upload_id=invoice.upload_id,
                status=cast(InvoiceStatus, invoice.status),  # the database allows only these
                supplier_code=view.supplier.code if view.supplier else None,
                supplier_name=invoice.supplier_name,
                supplier_gstin=invoice.supplier_gstin,
                invoice_no=invoice.invoice_no,
                invoice_date=invoice.invoice_date,
                subtotal=invoice.subtotal,
                gst_amount=invoice.gst_amount,
                grand_total=invoice.grand_total,
                marked_duplicate=invoice.marked_duplicate,
                notes=invoice.notes,
                lines_read_by=cast(Literal["table", "model"], invoice.lines_read_by),
                lines=[
                    InvoiceLineOut(
                        line_no=line.line_no,
                        description=line.description,
                        qty=line.qty,
                        rate=line.rate,
                        amount=line.amount,
                        sku=product.sku if product else None,
                        name=product.name if product else None,
                        matched_on=line.matched_on,
                        cost_price=product.cost_price if product else None,
                        last_rate=_decimal(checked.get(line.line_no, {}).get("last_rate")),
                        last_rate_from=checked.get(line.line_no, {}).get("last_rate_from"),
                        jump_percent=_decimal(checked.get(line.line_no, {}).get("jump_percent")),
                    )
                    for line, product in view.lines
                ],
                proposal_id=view.proposal.id if view.proposal else None,
                ready=numbers.get("ready"),
                price_jumps=numbers.get("price_jumps"),
                created_at=invoice.created_at,
            )
        )
    return InvoicesOut(items=items)


def _decimal(value: Any) -> Decimal | None:
    return Decimal(value) if value is not None else None
