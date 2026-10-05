"""When to reorder a product, and how much (company policy, section 1).

    average daily sales = units sold in the last 90 days / 90
    reorder point       = average daily sales x (supplier lead time + 3 safety days)
    reorder when          on hand + on order <= reorder point
    quantity            = sales for (lead time + 30 days) - on hand - on order,
                          rounded UP to the pack size

Decisions use exact whole-number arithmetic (no floating point), so a product exactly on
its reorder point is always treated the same way. Rounded figures are only for display.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class ReorderPolicy:
    window_days: int = 90  # sales history used for the average
    safety_days: int = 3
    cover_days: int = 30  # how long an order should last after it arrives
    owner_approval_above: Decimal = Decimal(100000)  # policy 1.5: bigger POs need the owner


DEFAULT_REORDER_POLICY = ReorderPolicy()  # the company policy as written


@dataclass(frozen=True)
class StockPosition:
    sku: str
    on_hand: int
    on_order: int
    sold_in_window: int  # units sold in the last `window_days` days
    lead_time_days: int
    pack_size: int
    cost_price: Decimal


@dataclass(frozen=True)
class ReorderAdvice:
    sku: str
    reorder: bool
    qty: int  # 0 when no reorder is needed
    avg_daily: Decimal  # 2 decimals, for display
    reorder_point: Decimal  # 1 decimal, for display
    days_of_cover: Decimal | None  # (on hand + on order) / average daily sales; None = no sales
    est_cost: Decimal
    needs_owner: bool  # estimated cost above the owner-approval limit


def check_reorder(
    position: StockPosition, policy: ReorderPolicy = DEFAULT_REORDER_POLICY
) -> ReorderAdvice:
    window = policy.window_days
    sold = position.sold_in_window
    available = position.on_hand + position.on_order

    # available <= sold/window * (lead + safety), multiplied out to stay in whole numbers
    reorder = sold > 0 and available * window <= sold * (
        position.lead_time_days + policy.safety_days
    )
    qty = 0
    if reorder:
        # needed = sold/window * (lead + cover) - available, rounded up to whole packs
        needed_times_window = (
            sold * (position.lead_time_days + policy.cover_days) - available * window
        )
        packs = -(-needed_times_window // (window * position.pack_size))  # ceiling division
        qty = max(packs, 0) * position.pack_size
    est_cost = position.cost_price * qty
    return ReorderAdvice(
        sku=position.sku,
        reorder=reorder and qty > 0,
        qty=qty,
        avg_daily=_round(Decimal(sold) / window, "0.01"),
        reorder_point=_round(
            Decimal(sold) * (position.lead_time_days + policy.safety_days) / window, "0.1"
        ),
        days_of_cover=_round(Decimal(available) * window / sold, "0.1") if sold else None,
        est_cost=est_cost,
        needs_owner=est_cost > policy.owner_approval_above,
    )


def _round(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
