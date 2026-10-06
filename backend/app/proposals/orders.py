"""Customer orders read from WhatsApp, as proposals: "confirm this order".

An order is created by the WhatsApp import and waits as `awaiting_confirmation`. Its proposal
shows the lines, an estimated value (calculated here, never by the model) and what needs
attention: a line without a product, something to ask the customer, an unknown sender, or a
customer on hold (policy 2.4). The owner can fix a line (choose its product, or remove it);
every fix is audited and refreshes the proposal, so what gets approved is what's on screen.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import audit_entry
from app.db.models import Customer, CustomerOrder, CustomerOrderLine, Product, Proposal
from app.domain.money import format_inr
from app.proposals.checks import CONFIRM_ORDER


class OrderNotFound(Exception):
    pass


class OrderLineNotFound(Exception):
    pass


class OrderNotEditable(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(f"This order is already {status.replace('_', ' ')}; it can't be changed.")


class UnknownProduct(Exception):
    def __init__(self, sku: str) -> None:
        super().__init__(f"There is no product {sku}.")


class OrderNotReady(Exception):
    """Approving would confirm something incomplete; the message says what to fix first."""


async def describe_order(session: AsyncSession, order: CustomerOrder) -> tuple[dict[str, Any], str]:
    """The proposal's numbers and its plain-language reason, from the order as it is now."""
    rows = (
        await session.execute(
            select(CustomerOrderLine, Product)
            .outerjoin(Product, Product.id == CustomerOrderLine.product_id)
            .where(CustomerOrderLine.order_id == order.id)
            .order_by(CustomerOrderLine.id)
        )
    ).all()
    customer = await session.get(Customer, order.customer_id) if order.customer_id else None
    lines = []
    value = Decimal(0)
    for line, product in rows:
        amount = product.sell_price * line.qty if product else None
        value += amount or 0
        lines.append(
            {
                "line_id": line.id,
                "written": line.written,
                "qty": line.qty,
                "unit_written": line.unit_written,
                "sku": product.sku if product else None,
                "name": product.name if product else None,
                "unit": product.unit if product else None,
                "matched_on": line.matched_on,
                "amount": str(amount) if amount is not None else None,
            }
        )
    unmatched = [line["written"] for line in lines if line["sku"] is None]
    on_hold = bool(customer and customer.on_hold)
    attention = []
    if customer is None:
        attention.append(f"'{order.sender}' is not a known customer")
    if on_hold:
        attention.append("this customer is ON HOLD, so dispatch needs the owner (policy 2.4)")
    if unmatched:
        attention.append(f"choose the product for: {', '.join(repr(w) for w in unmatched)}")
    if order.unclear:
        attention.append(f"ask the customer about: {'; '.join(order.unclear)}")
    by_model = [line["written"] for line in lines if line["matched_on"] == "model"]
    if by_model:
        attention.append(f"check the language model's match for: {', '.join(by_model)}")

    who = customer.shop_name if customer else order.sender
    reason = (
        f"Confirm {who}'s WhatsApp order of {order.first_sent_at:%d %b}: "
        f"{len(lines)} line{'s' if len(lines) != 1 else ''}, about {format_inr(value)} at list "
        "prices."
    )
    if attention:
        reason += " Before approving: " + "; ".join(attention) + "."
    numbers = {
        "sender": order.sender,
        "customer_code": customer.code if customer else None,
        "lines": lines,
        "est_value": str(value),
        "unclear": list(order.unclear),
        "customer_on_hold": on_hold,
        "ready": not unmatched and customer is not None,
    }
    return numbers, reason


async def create_order_proposal(
    session: AsyncSession, order: CustomerOrder, basis: dict[str, Any]
) -> Proposal:
    numbers, reason = await describe_order(session, order)
    proposal = Proposal(
        kind=CONFIRM_ORDER, order_id=order.id, numbers=numbers, basis=basis, reason=reason
    )
    session.add(proposal)
    return proposal


async def set_order_line(
    session: AsyncSession,
    order_id: int,
    line_id: int,
    *,
    sku: str | None,
    remove: bool,
    actor: str,
    qty: int | None = None,
) -> CustomerOrder:
    """The owner chooses a line's product (sku), corrects its quantity, or removes it.
    Audited."""
    order = await session.scalar(
        select(CustomerOrder).where(CustomerOrder.id == order_id).with_for_update()
    )
    if order is None:
        raise OrderNotFound(order_id)
    if order.status != "awaiting_confirmation":
        raise OrderNotEditable(order.status)
    line = await session.get(CustomerOrderLine, line_id)
    if line is None or line.order_id != order.id:
        raise OrderLineNotFound(line_id)
    before = {"product_id": line.product_id, "qty": line.qty, "matched_on": line.matched_on}
    after: dict[str, Any] = {}
    if remove:
        await session.delete(line)
        after["removed"] = True
    if not remove and sku:
        product = await session.scalar(select(Product).where(Product.sku == sku))
        if product is None:
            raise UnknownProduct(sku)
        line.product_id, line.matched_on = product.id, "owner"
        after |= {"product_id": product.id, "sku": product.sku, "matched_on": "owner"}
    if not remove and qty is not None:
        line.qty = qty
        after["qty"] = qty
    session.add(
        audit_entry(
            actor=actor,
            action="order.line_" + ("remove" if remove else "change"),
            entity_type="customer_order_line",
            entity_id=line_id,
            before=before,
            after={"order_id": order.id, "written": line.written, **after},
        )
    )
    await session.flush()
    proposal = await session.scalar(
        select(Proposal).where(Proposal.order_id == order.id, Proposal.status == "pending")
    )
    if proposal is not None:
        proposal.numbers, proposal.reason = await describe_order(session, order)
    await session.commit()
    return order


async def confirm_order(session: AsyncSession, proposal: Proposal) -> dict[str, Any]:
    """The approve step for an order proposal; refuses if anything is still incomplete."""
    order = await session.scalar(
        select(CustomerOrder).where(CustomerOrder.id == proposal.order_id).with_for_update()
    )
    assert order is not None  # a foreign key guarantees it
    numbers, _ = await describe_order(session, order)
    if numbers["customer_code"] is None:
        raise OrderNotReady(
            f"'{order.sender}' is not a known customer. Add them to the customers file first."
        )
    unmatched = [line["written"] for line in numbers["lines"] if line["sku"] is None]
    if unmatched:
        raise OrderNotReady(
            "Choose the product for "
            + ", ".join(repr(w) for w in unmatched)
            + ", or remove the line, before confirming."
        )
    if not numbers["lines"]:
        raise OrderNotReady("The order has no lines left; reject it instead.")
    order.status = "confirmed"
    return {"order_id": order.id, "lines": numbers["lines"], "est_value": numbers["est_value"]}


async def reject_order(session: AsyncSession, proposal: Proposal) -> dict[str, Any]:
    order = await session.get(CustomerOrder, proposal.order_id, with_for_update=True)
    assert order is not None
    order.status = "rejected"
    return {"order_id": order.id}
