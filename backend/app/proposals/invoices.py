"""Supplier invoices as proposals: "approve this invoice for payment".

When an invoice is saved (intake/invoice_import.py):
- the same supplier's earlier invoice with the same number makes it a DUPLICATE (policy 4.2):
  it is marked `duplicate`, reported, and gets no proposal, so it can never be paid;
- otherwise it gets an `approve_invoice` proposal showing, per line, the rate against the last
  purchase rate (the latest earlier invoice for that product, else the product master's cost
  price), with every rise of more than 10% flagged (policy 4.1).

Approving is refused while the invoice is incomplete (unknown supplier, a line without a
product, or figures that don't add up); a price jump doesn't block, it is shown so the owner
decides with it in view.
"""

from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Issue, Product, Proposal, Supplier, SupplierInvoice, SupplierInvoiceLine
from app.domain.anomalies import (
    EarlierInvoice,
    PurchaseRate,
    duplicate_of,
    last_purchase_rate,
    price_jump,
)
from app.domain.money import format_inr
from app.intake.issues import IssueRecord, IssueType
from app.proposals.checks import APPROVE_INVOICE
from app.proposals.errors import InvoiceNotReady

_NOT_PAYABLE = ("duplicate", "rejected")


async def find_duplicate(session: AsyncSession, invoice: SupplierInvoice) -> EarlierInvoice | None:
    """An earlier invoice from the same supplier with the same number (policy 4.2)."""
    if invoice.supplier_id is None:
        return None
    rows = await session.execute(
        select(SupplierInvoice.id, Supplier.code, SupplierInvoice.invoice_no)
        .join(Supplier, Supplier.id == SupplierInvoice.supplier_id)
        .where(
            SupplierInvoice.supplier_id == invoice.supplier_id,
            SupplierInvoice.id != invoice.id,
            SupplierInvoice.status != "rejected",
        )
        .order_by(SupplierInvoice.id)
    )
    supplier_code = await session.scalar(
        select(Supplier.code).where(Supplier.id == invoice.supplier_id)
    )
    return duplicate_of(supplier_code, invoice.invoice_no, [EarlierInvoice(*row) for row in rows])


def duplicate_issue(invoice: SupplierInvoice, original: EarlierInvoice) -> IssueRecord:
    return IssueRecord(
        IssueType.DUPLICATE_INVOICE,
        f"Invoice {invoice.invoice_no} from {original.supplier_code} was already received "
        f"(invoice #{original.invoice_id}). This copy is marked duplicate and will not be paid "
        "(policy 4.2).",
    )


def copy_without_original_issue(invoice: SupplierInvoice) -> IssueRecord:
    return IssueRecord(
        IssueType.DUPLICATE_COPY_WITHOUT_ORIGINAL,
        f"The PDF is stamped DUPLICATE COPY, but no earlier invoice {invoice.invoice_no} from "
        f"'{invoice.supplier_name}' was found, so this one can be approved. Check that the "
        "original wasn't paid outside OpsPilot.",
    )


async def describe_invoice(
    session: AsyncSession, invoice: SupplierInvoice
) -> tuple[dict[str, Any], str]:
    """The proposal's numbers and plain-language reason, from the invoice as saved."""
    supplier = await session.get(Supplier, invoice.supplier_id) if invoice.supplier_id else None
    rows = (
        await session.execute(
            select(SupplierInvoiceLine, Product)
            .outerjoin(Product, Product.id == SupplierInvoiceLine.product_id)
            .where(SupplierInvoiceLine.invoice_id == invoice.id)
            .order_by(SupplierInvoiceLine.line_no)
        )
    ).all()
    lines, jumps = [], []
    for line, product in rows:
        entry: dict[str, Any] = {
            "line_no": line.line_no,
            "description": line.description,
            "sku": product.sku if product else None,
            "name": product.name if product else None,
            "qty": str(line.qty),
            "rate": str(line.rate),
            "amount": str(line.amount),
            "last_rate": None,
            "last_rate_from": None,
            "jump_percent": None,
        }
        if product is not None:
            last = last_purchase_rate(
                await _earlier_rates(session, invoice, product.id), product.cost_price
            )
            entry["last_rate"] = str(last.rate)
            entry["last_rate_from"] = (
                f"invoice {last.invoice_no} of {last.on:%d %b %Y}"
                if last.on is not None
                else "the product master's cost price"
            )
            jump = price_jump(line.rate, last)
            if jump is not None:
                entry["jump_percent"] = str(jump.percent)
                jumps.append(
                    f"{product.name} at {format_inr(line.rate)} against {format_inr(last.rate)} "
                    f"(+{jump.percent}%)"
                )
        lines.append(entry)

    arithmetic = list(
        (
            await session.scalars(
                select(Issue.detail).where(
                    Issue.upload_id == invoice.upload_id, Issue.issue_type == "invoice_arithmetic"
                )
            )
        ).all()
    )
    unmatched = [entry["description"] for entry in lines if entry["sku"] is None]
    blockers = []
    if supplier is None:
        blockers.append(f"'{invoice.supplier_name}' is not a known supplier")
    if unmatched:
        blockers.append(f"choose the product for: {', '.join(repr(d) for d in unmatched)}")
    if arithmetic:
        blockers.append("the figures don't add up: " + " ".join(arithmetic))

    who = supplier.name if supplier else invoice.supplier_name
    dated = f" of {invoice.invoice_date:%d %b}" if invoice.invoice_date else ""
    reason = (
        f"Approve {who}'s invoice {invoice.invoice_no}{dated} for payment: "
        f"{format_inr(invoice.grand_total)} including GST."
    )
    if jumps:
        reason += (
            f" {len(jumps)} rate{'s are' if len(jumps) > 1 else ' is'} more than 10% above the "
            f"last purchase rate (policy 4.1): {'; '.join(jumps)}."
        )
    else:
        reason += " Every rate is within 10% of the last purchase rate."
    if invoice.marked_duplicate:
        reason += " The PDF is marked DUPLICATE COPY, but no original was found."
    if blockers:
        reason += " Before approving: " + "; ".join(blockers) + "."
    numbers = {
        "supplier_code": supplier.code if supplier else None,
        "supplier_name": who,
        "supplier_gstin": invoice.supplier_gstin,
        "invoice_no": invoice.invoice_no,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "subtotal": str(invoice.subtotal),
        "gst_amount": str(invoice.gst_amount),
        "grand_total": str(invoice.grand_total),
        "lines": lines,
        "price_jumps": len(jumps),
        "needs_owner": bool(jumps),
        "arithmetic_problems": arithmetic,
        "marked_duplicate": invoice.marked_duplicate,
        "ready": not blockers,
    }
    return numbers, reason


async def _earlier_rates(
    session: AsyncSession, invoice: SupplierInvoice, product_id: int
) -> list[PurchaseRate]:
    """Rates for the product on payable invoices dated before this one."""
    before = (
        or_(
            SupplierInvoice.invoice_date < invoice.invoice_date,
            (SupplierInvoice.invoice_date == invoice.invoice_date)
            & (SupplierInvoice.id < invoice.id),
        )
        if invoice.invoice_date is not None
        else SupplierInvoice.id < invoice.id
    )
    rows = await session.execute(
        select(SupplierInvoiceLine.rate, SupplierInvoice.invoice_date, SupplierInvoice.invoice_no)
        .join(SupplierInvoice, SupplierInvoice.id == SupplierInvoiceLine.invoice_id)
        .where(
            SupplierInvoiceLine.product_id == product_id,
            SupplierInvoice.id != invoice.id,
            SupplierInvoice.status.not_in(_NOT_PAYABLE),
            SupplierInvoice.invoice_date.is_not(None),
            before,
        )
    )
    return [PurchaseRate(rate, on, number) for rate, on, number in rows.all()]


async def create_invoice_proposal(
    session: AsyncSession, invoice: SupplierInvoice, basis: dict[str, Any]
) -> Proposal:
    numbers, reason = await describe_invoice(session, invoice)
    proposal = Proposal(
        kind=APPROVE_INVOICE, invoice_id=invoice.id, numbers=numbers, basis=basis, reason=reason
    )
    session.add(proposal)
    return proposal


async def approve_invoice(session: AsyncSession, proposal: Proposal) -> dict[str, Any]:
    invoice = await session.get(SupplierInvoice, proposal.invoice_id, with_for_update=True)
    assert invoice is not None  # a foreign key guarantees it
    numbers, _ = await describe_invoice(session, invoice)
    if not numbers["ready"]:
        problems = []
        if numbers["supplier_code"] is None:
            problems.append(f"'{invoice.supplier_name}' is not a known supplier")
        problems += [
            f"line {line['line_no']} has no product" for line in numbers["lines"] if not line["sku"]
        ]
        problems += numbers["arithmetic_problems"]
        raise InvoiceNotReady(
            "This invoice can't be approved for payment yet: " + "; ".join(problems) + ". "
            "Reject it and ask the supplier for a corrected invoice if the figures are wrong."
        )
    invoice.status = "approved_for_payment"
    return {
        "invoice_id": invoice.id,
        "grand_total": numbers["grand_total"],
        "price_jumps_accepted": numbers["price_jumps"],
    }


async def reject_invoice(session: AsyncSession, proposal: Proposal) -> dict[str, Any]:
    invoice = await session.get(SupplierInvoice, proposal.invoice_id, with_for_update=True)
    assert invoice is not None
    invoice.status = "rejected"
    return {"invoice_id": invoice.id}


def today_basis(today: date, upload_id: int) -> dict[str, Any]:
    return {"today": today.isoformat(), "invoice_upload_id": upload_id}
