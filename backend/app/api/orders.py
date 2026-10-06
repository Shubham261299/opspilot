from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.api.errors import ApiError
from app.api.schemas import (
    EnquiriesOut,
    EnquiryOut,
    OrderLineChangeIn,
    OrderLineOut,
    OrderOut,
    OrdersOut,
)
from app.db.audit import OWNER
from app.db.queries import OrderView, list_enquiries, list_orders
from app.proposals.orders import (
    OrderLineNotFound,
    OrderNotEditable,
    OrderNotFound,
    UnknownProduct,
    set_order_line,
)

router = APIRouter(tags=["orders"])
OrderStatus = Literal["awaiting_confirmation", "confirmed", "rejected"]


@router.get("/orders")
async def get_orders(
    session: SessionDep, status: Annotated[OrderStatus | None, Query()] = None
) -> OrdersOut:
    """Orders read from WhatsApp chats, newest first."""
    return OrdersOut(items=[_out(view) for view in await list_orders(session, status)])


@router.patch(
    "/orders/{order_id}/lines/{line_id}",
    responses={
        404: {"description": "No such order, line or product"},
        409: {"description": "The order is already confirmed or rejected"},
    },
)
async def change_order_line(
    order_id: int, line_id: int, body: OrderLineChangeIn, session: SessionDep
) -> OrderOut:
    """Fix a line: choose its product, correct its quantity, or remove it. Audited, and the
    order's proposal is refreshed."""
    if not body.remove and not body.sku and body.qty is None:
        raise ApiError(
            422, "change_required", "Give the product's SKU or the quantity, or set remove."
        )
    try:
        await set_order_line(
            session, order_id, line_id, sku=body.sku, qty=body.qty, remove=body.remove, actor=OWNER
        )
    except (OrderNotFound, OrderLineNotFound, UnknownProduct) as exc:
        await session.rollback()
        message = str(exc) if isinstance(exc, UnknownProduct) else "No such order line."
        raise ApiError(404, "not_found", message) from exc
    except OrderNotEditable as exc:
        await session.rollback()
        raise ApiError(409, "order_not_editable", str(exc)) from exc
    [view] = await list_orders(session, order_id=order_id)
    return _out(view)


@router.get("/enquiries")
async def get_enquiries(session: SessionDep) -> EnquiriesOut:
    """Questions customers asked in WhatsApp (prices, stock, products we may not sell)."""
    return EnquiriesOut(
        items=[
            EnquiryOut(
                id=e.id,
                upload_id=e.upload_id,
                sender=e.sender,
                customer_code=code,
                text=e.text,
                source_line=e.source_line,
                created_at=e.created_at,
            )
            for e, code in await list_enquiries(session)
        ]
    )


def _out(view: OrderView) -> OrderOut:
    order = view.order
    return OrderOut(
        id=order.id,
        upload_id=order.upload_id,
        status=cast(OrderStatus, order.status),  # the database allows only these
        sender=order.sender,
        customer_code=view.customer.code if view.customer else None,
        customer_name=view.customer.shop_name if view.customer else None,
        first_sent_at=order.first_sent_at,
        source_lines=order.source_lines,
        unclear=order.unclear,
        lines=[
            OrderLineOut(
                id=line.id,
                written=line.written,
                qty=line.qty,
                unit_written=line.unit_written,
                sku=product.sku if product else None,
                name=product.name if product else None,
                matched_on=line.matched_on,
            )
            for line, product in view.lines
        ],
        proposal_id=view.proposal_id,
    )
