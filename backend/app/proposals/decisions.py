"""Approve or reject a proposal: the only way anything in OpsPilot acts.

Each decision is one transaction: the proposal's status, what approving creates (a purchase
order, a hold on the customer, or a reminder ready to send) and an audit_log row with the
before and after state. Either all of it is saved or none of it.

The proposal row is locked first (SELECT ... FOR UPDATE). If two people click Approve at
the same moment, the second waits for the first to finish, then sees the proposal is no
longer pending and gets an error, so one proposal can never create two purchase orders.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import audit_entry
from app.db.models import (
    Customer,
    PaymentReminder,
    Product,
    Proposal,
    PurchaseOrder,
    PurchaseOrderLine,
)
from app.domain.money import format_inr
from app.proposals.checks import CONFIRM_ORDER, HOLD_ORDERS, PAYMENT_REMINDER, REORDER
from app.proposals.orders import confirm_order, reject_order

logger = logging.getLogger(__name__)


class Decide(Protocol):
    """approve() and reject() have this shape, so the API can call either one."""

    async def __call__(
        self, session: AsyncSession, proposal_id: int, *, actor: str, note: str | None = None
    ) -> Proposal: ...


class ProposalNotFound(Exception):
    pass


class ProposalNotPending(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(f"This proposal is already {status}.")
        self.status = status


async def approve(
    session: AsyncSession, proposal_id: int, *, actor: str, note: str | None = None
) -> Proposal:
    proposal = await _lock_pending(session, proposal_id)
    created: dict[str, Any]
    if proposal.kind == REORDER:
        created = await _create_purchase_order(session, proposal, actor)
    elif proposal.kind == HOLD_ORDERS:
        created = await _put_on_hold(session, proposal)
    elif proposal.kind == PAYMENT_REMINDER:
        created = await _prepare_reminder(session, proposal)
    elif proposal.kind == CONFIRM_ORDER:
        created = await confirm_order(session, proposal)  # may refuse: OrderNotReady
    else:  # the database only allows the four kinds above
        raise ValueError(f"unknown proposal kind {proposal.kind!r}")
    return await _decide(session, proposal, "approved", actor, note, created)


async def reject(
    session: AsyncSession, proposal_id: int, *, actor: str, note: str | None = None
) -> Proposal:
    proposal = await _lock_pending(session, proposal_id)
    undone = await reject_order(session, proposal) if proposal.kind == CONFIRM_ORDER else {}
    return await _decide(session, proposal, "rejected", actor, note, undone)


async def _lock_pending(session: AsyncSession, proposal_id: int) -> Proposal:
    proposal = await session.scalar(
        select(Proposal).where(Proposal.id == proposal_id).with_for_update()
    )
    if proposal is None:
        raise ProposalNotFound(proposal_id)
    if proposal.status != "pending":
        raise ProposalNotPending(proposal.status)
    return proposal


async def _decide(
    session: AsyncSession,
    proposal: Proposal,
    status: str,
    actor: str,
    note: str | None,
    created: dict[str, Any],
) -> Proposal:
    proposal.status = status
    proposal.decided_at = datetime.now(UTC)
    proposal.decided_by = actor
    proposal.decision_note = note.strip() if note and note.strip() else None
    session.add(
        audit_entry(
            actor=actor,
            action=f"proposal.{'approve' if status == 'approved' else 'reject'}",
            entity_type="proposal",
            entity_id=proposal.id,
            before={"status": "pending", "kind": proposal.kind, "numbers": proposal.numbers},
            after={"status": status, "note": proposal.decision_note, **created},
        )
    )
    await session.commit()
    logger.info(
        "proposal decided",
        extra={"proposal_id": proposal.id, "kind": proposal.kind, "status": status},
    )
    return proposal


async def _create_purchase_order(
    session: AsyncSession, proposal: Proposal, actor: str
) -> dict[str, Any]:
    product = await session.get(Product, proposal.product_id)
    assert product is not None  # a foreign key guarantees it
    order = PurchaseOrder(
        supplier_id=product.supplier_id, proposal_id=proposal.id, created_by=actor
    )
    session.add(order)
    await session.flush()
    session.add(
        PurchaseOrderLine(
            purchase_order_id=order.id,
            product_id=product.id,
            qty=proposal.numbers["qty"],
            unit_cost=product.cost_price,
        )
    )
    await session.flush()
    return {"purchase_order_id": order.id}


async def _put_on_hold(session: AsyncSession, proposal: Proposal) -> dict[str, Any]:
    customer = await session.get(Customer, proposal.customer_id, with_for_update=True)
    assert customer is not None
    before = {"on_hold": customer.on_hold, "hold_reason": customer.hold_reason}
    customer.on_hold = True
    customer.hold_reason = proposal.reason
    return {"customer": customer.code, "customer_before": before, "on_hold": True}


async def _prepare_reminder(session: AsyncSession, proposal: Proposal) -> dict[str, Any]:
    customer = await session.get(Customer, proposal.customer_id)
    assert customer is not None
    reminder = PaymentReminder(
        customer_id=customer.id,
        proposal_id=proposal.id,
        # The language model's draft, if it passed the checks; else the template.
        message=proposal.draft_message or reminder_message(customer, proposal.numbers),
    )
    session.add(reminder)
    await session.flush()
    return {"payment_reminder_id": reminder.id, "customer": customer.code}


def reminder_message(customer: Customer, numbers: dict[str, Any]) -> str:
    """A polite reminder in simple English (policy 2.5). The LLM rewrites it from week 3."""
    bills = [b for b in numbers["overdue_bills"] if b["days_overdue"] >= 7] or numbers[
        "overdue_bills"
    ]
    listed = ", ".join(
        f"{b['bill_no']} dated {datetime.fromisoformat(b['bill_date']):%d %b} "
        f"({format_inr(Decimal(b['balance']))})"
        for b in bills
    )
    name = customer.contact_person or customer.shop_name
    return (
        f"Namaste {name} ji, this is a gentle reminder from Sharma Traders. Payment for bill(s) "
        f"{listed} is now due. Your total outstanding is "
        f"{format_inr(Decimal(numbers['total_balance']))}. Kindly arrange the payment at your "
        "convenience. Thank you for your business!"
    )
