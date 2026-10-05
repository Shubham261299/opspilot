"""Run checks: apply the reorder and payment rules to the current data and keep the list of
pending proposals up to date.

The rules themselves are pure functions in app/domain/. This module only gathers their
inputs from the database and reconciles the results with the proposals already pending:

- still needed, same numbers  -> the pending proposal is kept as it is
- still needed, new numbers   -> the old one is marked `superseded`, a new one is created
- no longer needed            -> the pending one is marked `superseded`
- newly needed                -> created

Running checks twice in a row therefore changes nothing the second time (it is idempotent).
Nothing is ever approved here: proposals wait for a human.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import audit_entry
from app.db.models import (
    Customer,
    CustomerBill,
    OpenPoNote,
    Product,
    Proposal,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesLine,
    StockLevel,
    Supplier,
)
from app.db.queries import OUTSTANDING_DUES, SALES_HISTORY, STOCK_REGISTER, current_upload
from app.domain.credit import OpenBill, PaymentAdvice, check_payment
from app.domain.money import format_inr
from app.domain.reorder import DEFAULT_REORDER_POLICY, ReorderAdvice, StockPosition, check_reorder

logger = logging.getLogger(__name__)

REORDER = "reorder"
PAYMENT_REMINDER = "payment_reminder"
HOLD_ORDERS = "hold_orders"
_RUN_LOCK = 4_242_001  # any fixed number; identifies the "run checks" lock in Postgres


@dataclass(frozen=True)
class Wanted:
    """A proposal the rules ask for right now."""

    kind: str
    product_id: int | None
    customer_id: int | None
    numbers: dict[str, Any]
    reason: str


@dataclass
class RunResult:
    created: list[int] = field(default_factory=list)
    unchanged: list[int] = field(default_factory=list)
    superseded: list[int] = field(default_factory=list)
    already_decided: list[int] = field(default_factory=list)  # same situation, decided before
    not_checked: list[str] = field(default_factory=list)  # why some checks couldn't run


async def run_checks(session: AsyncSession, *, today: date, actor: str) -> RunResult:
    # Two runs at the same moment would both try to create the same proposals. This lock,
    # held until the transaction ends, makes a second run wait for the first to finish.
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _RUN_LOCK})
    result = RunResult()
    basis: dict[str, Any] = {"today": today.isoformat()}
    wanted = await _reorders_wanted(session, today, basis, result)
    wanted += await _payments_wanted(session, today, basis, result)

    pending = (await session.scalars(select(Proposal).where(Proposal.status == "pending"))).all()
    by_subject = {(p.kind, p.product_id, p.customer_id): p for p in pending}
    last_decided = await _last_decided(session)
    wanted_keys = set()
    for want in wanted:
        key = (want.kind, want.product_id, want.customer_id)
        wanted_keys.add(key)
        existing = by_subject.get(key)
        if existing is not None and existing.numbers == want.numbers:
            existing.reason = want.reason  # same numbers; only the wording can differ
            result.unchanged.append(existing.id)
            continue
        decided = last_decided.get(key)
        if existing is None and decided is not None and decided.numbers == want.numbers:
            # Already approved or rejected in exactly this situation: don't ask again.
            result.already_decided.append(decided.id)
            continue
        if existing is not None:
            existing.status = "superseded"
            result.superseded.append(existing.id)
            await session.flush()  # free the "one pending per subject" slot first
        proposal = Proposal(
            kind=want.kind,
            product_id=want.product_id,
            customer_id=want.customer_id,
            numbers=want.numbers,
            basis=basis,
            reason=want.reason,
        )
        session.add(proposal)
        await session.flush()
        result.created.append(proposal.id)
    for key, proposal in by_subject.items():
        if key not in wanted_keys:
            proposal.status = "superseded"
            result.superseded.append(proposal.id)

    session.add(
        audit_entry(
            actor=actor,
            action="proposals.run",
            entity_type="proposals",
            entity_id=None,
            after={
                "basis": basis,
                "created": result.created,
                "superseded": result.superseded,
                "unchanged": len(result.unchanged),
                "already_decided": result.already_decided,
                "not_checked": result.not_checked,
            },
        )
    )
    await session.commit()
    logger.info(
        "checks run",
        extra={
            "proposals_created": len(result.created),
            "proposals_superseded": len(result.superseded),
        },
    )
    return result


async def _last_decided(
    session: AsyncSession,
) -> dict[tuple[str, int | None, int | None], Proposal]:
    """The most recent approved or rejected proposal for each kind and subject."""
    decided = await session.scalars(
        select(Proposal)
        .where(Proposal.status.in_(("approved", "rejected")))
        .order_by(Proposal.decided_at, Proposal.id)
    )
    return {(p.kind, p.product_id, p.customer_id): p for p in decided.all()}  # later wins


# Reorders -------------------------------------------------------------------------


async def _reorders_wanted(
    session: AsyncSession, today: date, basis: dict[str, Any], result: RunResult
) -> list[Wanted]:
    stock = await current_upload(session, STOCK_REGISTER)
    sales = await current_upload(session, SALES_HISTORY)
    if stock is None or sales is None:
        result.not_checked.append("Reorders: upload a stock register and the sales history first.")
        return []
    basis |= {"stock_upload_id": stock.id, "sales_upload_id": sales.id}

    on_hand = dict(
        (
            await session.execute(
                select(StockLevel.product_id, StockLevel.qty_on_hand).where(
                    StockLevel.upload_id == stock.id
                )
            )
        ).all()
    )
    on_order = await _on_order(session, stock.id)
    window_start = today - timedelta(days=DEFAULT_REORDER_POLICY.window_days - 1)
    sold = dict(
        (
            await session.execute(
                select(SalesLine.product_id, func.sum(SalesLine.qty))
                .where(
                    SalesLine.upload_id == sales.id,
                    SalesLine.sale_date >= window_start,
                    SalesLine.sale_date <= today,
                )
                .group_by(SalesLine.product_id)
            )
        ).all()
    )
    rows = (
        await session.execute(select(Product, Supplier).join(Supplier).order_by(Product.sku))
    ).all()

    wanted = []
    no_count = []
    for product, supplier in rows:
        if product.id not in on_hand:
            no_count.append(product.sku)
            continue
        advice = check_reorder(
            StockPosition(
                sku=product.sku,
                on_hand=on_hand[product.id],
                on_order=on_order.get(product.id, 0),
                sold_in_window=int(sold.get(product.id, 0)),
                lead_time_days=supplier.lead_time_days,
                pack_size=product.pack_size,
                cost_price=product.cost_price,
            )
        )
        if advice.reorder:
            wanted.append(_reorder_proposal(product, supplier, advice, on_hand, on_order))
    if no_count:
        result.not_checked.append(
            f"Reorders: no trusted stock count for {', '.join(no_count)} (see the Issues page)."
        )
    return wanted


async def _on_order(session: AsyncSession, stock_upload_id: int) -> dict[int, int]:
    """Stock already on order: PO notes in the stock sheet plus POs approved in OpsPilot."""
    totals: dict[int, int] = defaultdict(int)
    notes = await session.execute(
        select(OpenPoNote.product_id, func.sum(OpenPoNote.qty))
        .where(OpenPoNote.upload_id == stock_upload_id)
        .group_by(OpenPoNote.product_id)
    )
    approved = await session.execute(
        select(PurchaseOrderLine.product_id, func.sum(PurchaseOrderLine.qty))
        .join(PurchaseOrder)
        .where(PurchaseOrder.status.in_(("approved", "sent")))
        .group_by(PurchaseOrderLine.product_id)
    )
    for product_id, qty in [*notes.all(), *approved.all()]:
        totals[product_id] += int(qty)
    return totals


def _reorder_proposal(
    product: Product,
    supplier: Supplier,
    advice: ReorderAdvice,
    on_hand: dict[int, int],
    on_order: dict[int, int],
) -> Wanted:
    have, coming = on_hand[product.id], on_order.get(product.id, 0)
    unit = product.unit if advice.qty == 1 else f"{product.unit}s"
    owner = (
        " Above ₹1,00,000, so the owner must approve it (policy 1.5)." if advice.needs_owner else ""
    )
    reason = (
        f"{have} on hand + {coming} on order is at or below the reorder point of "
        f"{advice.reorder_point} ({advice.avg_daily} sold a day × ({supplier.lead_time_days} "
        f"days lead time + {DEFAULT_REORDER_POLICY.safety_days} safety days)). Order "
        f"{advice.qty} {unit} ({advice.qty // product.pack_size} packs of {product.pack_size}) "
        f"from {supplier.name} to cover {supplier.lead_time_days} + "
        f"{DEFAULT_REORDER_POLICY.cover_days} days: about {format_inr(advice.est_cost)}.{owner}"
    )
    return Wanted(
        kind=REORDER,
        product_id=product.id,
        customer_id=None,
        reason=reason,
        numbers={
            "on_hand": have,
            "on_order": coming,
            "avg_daily": str(advice.avg_daily),
            "lead_time_days": supplier.lead_time_days,
            "reorder_point": str(advice.reorder_point),
            "days_of_cover": None if advice.days_of_cover is None else str(advice.days_of_cover),
            "qty": advice.qty,
            "pack_size": product.pack_size,
            "unit": product.unit,
            "unit_cost": str(product.cost_price),
            "est_cost": str(advice.est_cost),
            "needs_owner": advice.needs_owner,
            "supplier_code": supplier.code,
            "supplier_name": supplier.name,
        },
    )


# Payments -------------------------------------------------------------------------


async def _payments_wanted(
    session: AsyncSession, today: date, basis: dict[str, Any], result: RunResult
) -> list[Wanted]:
    dues = await current_upload(session, OUTSTANDING_DUES)
    if dues is None:
        result.not_checked.append("Payments: upload the customers and the outstanding dues first.")
        return []
    basis["dues_upload_id"] = dues.id
    bills: dict[int, list[OpenBill]] = defaultdict(list)
    for bill in (
        await session.scalars(select(CustomerBill).where(CustomerBill.upload_id == dues.id))
    ).all():
        bills[bill.customer_id].append(OpenBill(bill.bill_no, bill.bill_date, bill.balance))

    wanted = []
    for customer in (await session.scalars(select(Customer).order_by(Customer.code))).all():
        advice = check_payment(
            bills[customer.id], customer.credit_limit, customer.credit_days, today
        )
        if advice.action is None:
            continue
        if advice.action == "HOLD_NEW_ORDERS" and customer.on_hold:
            continue  # already on hold
        wanted.append(_payment_proposal(customer, advice))
    return wanted


def _payment_proposal(customer: Customer, advice: PaymentAdvice) -> Wanted:
    hold = advice.action == "HOLD_NEW_ORDERS"
    overdue = ", ".join(f"{b.bill_no} ({b.days_overdue} days)" for b in advice.overdue_bills)
    if hold:
        reason = f"Put new orders on hold: {' and '.join(advice.reasons)}."
        if not advice.over_limit:
            reason += (
                f" Outstanding {format_inr(advice.total_balance)} "
                f"(limit {format_inr(advice.credit_limit)})."
            )
    else:
        reason = (
            f"Send a polite payment reminder: {advice.reasons[0]}. Outstanding "
            f"{format_inr(advice.total_balance)}."
        )
    if overdue:
        reason += f" Overdue bills: {overdue}."
    return Wanted(
        kind=HOLD_ORDERS if hold else PAYMENT_REMINDER,
        product_id=None,
        customer_id=customer.id,
        reason=reason,
        numbers={
            "total_balance": str(advice.total_balance),
            "credit_limit": str(advice.credit_limit),
            "credit_days": customer.credit_days,
            "over_limit": advice.over_limit,
            "max_days_overdue": advice.max_days_overdue,
            "overdue_bills": [
                {
                    "bill_no": b.bill_no,
                    "bill_date": b.bill_date.isoformat(),
                    "balance": str(b.balance),
                    "days_overdue": b.days_overdue,
                }
                for b in advice.overdue_bills
            ],
        },
    )
