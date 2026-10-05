from typing import Annotated, cast

from fastapi import APIRouter, Query

from app.api.deps import SessionDep, TodayDep
from app.api.errors import ApiError
from app.api.schemas import (
    DecisionIn,
    ProposalKind,
    ProposalOut,
    ProposalsOut,
    ProposalStatus,
    ProposalSubjectOut,
    PurchaseOrderLineOut,
    PurchaseOrderOut,
    PurchaseOrdersOut,
    RunChecksOut,
    SupplierOut,
)
from app.db.audit import OWNER
from app.db.queries import (
    ProposalView,
    get_proposal_view,
    list_proposals,
    list_purchase_orders,
)
from app.proposals import decisions
from app.proposals.checks import run_checks

router = APIRouter(tags=["proposals"])

_DECISION_ERRORS: dict[int | str, dict[str, str]] = {
    404: {"description": "No proposal with this id"},
    409: {"description": "Already approved, rejected or superseded"},
}


@router.post("/proposals/run")
async def run_proposal_checks(session: SessionDep, today: TodayDep) -> RunChecksOut:
    """Apply the reorder and payment rules to the current data. Creates proposals only;
    nothing is ordered, held or sent until a human approves."""
    result = await run_checks(session, today=today, actor=OWNER)
    pending = await list_proposals(session, "pending")
    return RunChecksOut(
        created=len(result.created),
        unchanged=len(result.unchanged),
        superseded=len(result.superseded),
        already_decided=len(result.already_decided),
        pending=len(pending),
        not_checked=result.not_checked,
    )


@router.get("/proposals")
async def get_proposals(
    session: SessionDep, status: Annotated[ProposalStatus, Query()] = "pending"
) -> ProposalsOut:
    """Proposals with one status: pending ones are the Approval Inbox."""
    return ProposalsOut(items=[_out(view) for view in await list_proposals(session, status)])


@router.post("/proposals/{proposal_id}/approve", responses=_DECISION_ERRORS)
async def approve_proposal(
    proposal_id: int, session: SessionDep, body: DecisionIn | None = None
) -> ProposalOut:
    """Approve: a reorder creates a purchase order, a hold puts the customer on hold, and a
    reminder is prepared for sending. Written to the audit log."""
    return await _decide(decisions.approve, proposal_id, session, body)


@router.post("/proposals/{proposal_id}/reject", responses=_DECISION_ERRORS)
async def reject_proposal(
    proposal_id: int, session: SessionDep, body: DecisionIn | None = None
) -> ProposalOut:
    """Reject: nothing happens except the decision being recorded, with the note."""
    return await _decide(decisions.reject, proposal_id, session, body)


@router.get("/purchase-orders")
async def get_purchase_orders(session: SessionDep) -> PurchaseOrdersOut:
    """Purchase orders created by approving reorder proposals, newest first."""
    items = []
    for view in await list_purchase_orders(session):
        lines = [
            PurchaseOrderLineOut(
                sku=product.sku,
                name=product.name,
                qty=line.qty,
                unit=product.unit,
                unit_cost=line.unit_cost,
                amount=line.unit_cost * line.qty,
            )
            for line, product in view.lines
        ]
        items.append(
            PurchaseOrderOut(
                id=view.order.id,
                status=view.order.status,
                supplier=SupplierOut(code=view.supplier.code, name=view.supplier.name),
                proposal_id=view.order.proposal_id,
                created_by=view.order.created_by,
                created_at=view.order.created_at,
                lines=lines,
                total=sum((line.amount for line in lines), start=0),
            )
        )
    return PurchaseOrdersOut(items=items)


async def _decide(
    action: decisions.Decide, proposal_id: int, session: SessionDep, body: DecisionIn | None
) -> ProposalOut:
    try:
        await action(session, proposal_id, actor=OWNER, note=body.note if body else None)
    except decisions.ProposalNotFound as exc:
        raise ApiError(
            404, "proposal_not_found", f"There is no proposal with id {proposal_id}."
        ) from exc
    except decisions.ProposalNotPending as exc:
        await session.rollback()
        raise ApiError(409, "proposal_already_decided", str(exc)) from exc
    view = await get_proposal_view(session, proposal_id)
    assert view is not None
    return _out(view)


def _out(view: ProposalView) -> ProposalOut:
    proposal = view.proposal
    if view.sku is not None:
        subject = ProposalSubjectOut(type="product", code=view.sku, name=view.product_name or "")
    else:
        subject = ProposalSubjectOut(
            type="customer", code=view.customer_code or "", name=view.customer_name or ""
        )
    return ProposalOut(
        id=proposal.id,
        kind=cast(ProposalKind, proposal.kind),  # the database allows only these kinds
        status=cast(ProposalStatus, proposal.status),
        subject=subject,
        numbers=proposal.numbers,
        reason=proposal.reason,
        basis=proposal.basis,
        created_at=proposal.created_at,
        decided_at=proposal.decided_at,
        decided_by=proposal.decided_by,
        decision_note=proposal.decision_note,
        purchase_order_id=view.purchase_order_id,
        payment_reminder_id=view.payment_reminder_id,
        reminder_message=view.reminder_message,
    )
