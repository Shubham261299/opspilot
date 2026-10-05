from dataclasses import replace
from decimal import Decimal

from app.domain.reorder import StockPosition, check_reorder

# Sells 90 in 90 days = 1 a day. Lead time 5 + 3 safety days -> reorder point 8.
POSITION = StockPosition(
    sku="ST-0001",
    on_hand=8,
    on_order=0,
    sold_in_window=90,
    lead_time_days=5,
    pack_size=10,
    cost_price=Decimal("100.00"),
)


def test_stock_exactly_at_the_reorder_point_is_reordered() -> None:
    advice = check_reorder(POSITION)
    assert (advice.reorder, advice.reorder_point) == (True, Decimal("8.0"))


def test_one_above_the_reorder_point_is_not() -> None:
    advice = check_reorder(replace(POSITION, on_hand=9))
    assert (advice.reorder, advice.qty, advice.est_cost) == (False, 0, Decimal(0))


def test_stock_on_order_counts_as_available() -> None:
    assert not check_reorder(replace(POSITION, on_hand=4, on_order=5)).reorder


def test_quantity_covers_lead_time_plus_30_days_rounded_up_to_packs() -> None:
    # need 1/day x 35 days = 35, minus 8 available = 27 -> 3 packs of 10
    advice = check_reorder(POSITION)
    assert (advice.qty, advice.est_cost) == (30, Decimal("3000.00"))


def test_a_product_that_never_sells_is_never_reordered() -> None:
    advice = check_reorder(replace(POSITION, on_hand=0, sold_in_window=0))
    assert (advice.reorder, advice.days_of_cover) == (False, None)


def test_figures_for_display_are_rounded() -> None:
    advice = check_reorder(replace(POSITION, sold_in_window=70, on_hand=3))  # 0.777... a day
    assert (advice.avg_daily, advice.reorder_point, advice.days_of_cover) == (
        Decimal("0.78"),
        Decimal("6.2"),
        Decimal("3.9"),
    )


def test_orders_above_one_lakh_need_the_owner() -> None:
    assert not check_reorder(replace(POSITION, cost_price=Decimal("3333.33"))).needs_owner
    assert check_reorder(replace(POSITION, cost_price=Decimal("3333.34"))).needs_owner
