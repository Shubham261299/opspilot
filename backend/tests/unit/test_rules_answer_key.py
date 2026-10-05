"""Score the reorder and payment rules against sample_data/answer_key.json.

The answer key is used ONLY in tests, never by the app. Everything else is built exactly
the way the app builds it: the cleaned stock register, the sales history, the customers and
the dues sheet, run through the pure functions in app/domain/.
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.db.seed import ProductRow, SupplierRow, read_csv_rows
from app.domain.catalog import Catalog
from app.domain.credit import OpenBill, PaymentAdvice, check_payment
from app.domain.reorder import ReorderAdvice, StockPosition, check_reorder
from app.intake.customers import parse_customers
from app.intake.outstanding_dues import parse_outstanding_dues
from app.intake.sales_history import parse_sales_history
from app.intake.stock_register import parse_stock_register

TODAY = date(2026, 9, 24)  # "today" in the sample data
ANSWER_KEY = json.loads(
    (Path(__file__).resolve().parents[3] / "sample_data" / "answer_key.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture(scope="module")
def reorder_advice(sample_data_dir: Path, catalog: Catalog) -> dict[str, ReorderAdvice]:
    suppliers = {s.code: s for s in read_csv_rows(sample_data_dir / "suppliers.csv", SupplierRow)}
    products = read_csv_rows(sample_data_dir / "product_master.csv", ProductRow)
    stock = parse_stock_register(
        (sample_data_dir / "stock_register.xlsx").read_bytes(), catalog, TODAY
    )
    on_hand = {row.sku: row.qty_on_hand for row in stock.stock_rows}
    on_order: dict[str, int] = defaultdict(int)
    for note in stock.po_notes:
        on_order[note.sku] += note.qty
    customers = parse_customers((sample_data_dir / "customers.xlsx").read_bytes()).customers
    sales = parse_sales_history(
        (sample_data_dir / "sales_history_90d.csv").read_bytes(),
        {c.code for c in customers},
        {p.sku for p in products},
    )
    window_start = TODAY - timedelta(days=89)  # 90 days, today included
    sold: dict[str, int] = defaultdict(int)
    for sale in sales.sales:
        if window_start <= sale.sale_date <= TODAY:
            sold[sale.sku] += sale.qty
    return {
        p.sku: check_reorder(
            StockPosition(
                sku=p.sku,
                on_hand=on_hand[p.sku],
                on_order=on_order[p.sku],
                sold_in_window=sold[p.sku],
                lead_time_days=suppliers[p.supplier_code].lead_time_days,
                pack_size=p.pack_size,
                cost_price=p.cost_price,
            )
        )
        for p in products
        if p.sku in on_hand  # a product without a trusted count can't be checked
    }


@pytest.fixture(scope="module")
def payment_advice(sample_data_dir: Path) -> dict[str, PaymentAdvice]:
    customers = parse_customers((sample_data_dir / "customers.xlsx").read_bytes()).customers
    dues = parse_outstanding_dues(
        (sample_data_dir / "outstanding_dues.xlsx").read_bytes(),
        {c.code: c.shop_name for c in customers},
        TODAY,
    )
    bills: dict[str, list[OpenBill]] = defaultdict(list)
    for bill in dues.bills:
        bills[bill.customer_code].append(OpenBill(bill.bill_no, bill.bill_date, bill.balance))
    return {
        c.code: check_payment(bills[c.code], c.credit_limit, c.credit_days, TODAY)
        for c in customers
    }


# Reorders --------------------------------------------------------------------------


def test_exactly_the_expected_products_are_reordered(
    reorder_advice: dict[str, ReorderAdvice],
) -> None:
    expected = {e["sku"] for e in ANSWER_KEY["expected_reorders"]}
    assert {sku for sku, advice in reorder_advice.items() if advice.reorder} == expected


@pytest.mark.parametrize("expected", ANSWER_KEY["expected_reorders"], ids=lambda e: e["sku"])
def test_reorder_figures_match(
    reorder_advice: dict[str, ReorderAdvice], expected: dict[str, Any]
) -> None:
    advice = reorder_advice[expected["sku"]]
    assert advice.qty == expected["reorder_qty"]
    assert advice.est_cost == Decimal(expected["est_cost"])
    assert advice.reorder_point == Decimal(str(expected["reorder_point"]))
    assert advice.avg_daily == Decimal(str(expected["avg_daily"]))
    # The key divides by the already-rounded daily average (3 / 0.78 = 3.8 for ST-0005); we use
    # the exact one (3 / 0.7778 = 3.9). Display rounding only, so allow 0.1.
    assert abs(advice.days_of_cover - Decimal(str(expected["days_of_cover"]))) <= Decimal("0.1")


def test_stock_already_on_order_prevents_a_reorder(
    reorder_advice: dict[str, ReorderAdvice],
) -> None:
    [open_po] = ANSWER_KEY["open_purchase_orders"]
    assert not reorder_advice[open_po["sku"]].reorder


# Payment actions ---------------------------------------------------------------------


def test_exactly_the_expected_customers_get_an_action(
    payment_advice: dict[str, PaymentAdvice],
) -> None:
    expected = {
        e["customer_id"]: e["expected_action"] for e in ANSWER_KEY["expected_payment_actions"]
    }
    actual = {code: a.action for code, a in payment_advice.items() if a.action is not None}
    assert actual == expected


@pytest.mark.parametrize(
    "expected", ANSWER_KEY["expected_payment_actions"], ids=lambda e: e["customer_id"]
)
def test_payment_figures_match(
    payment_advice: dict[str, PaymentAdvice], expected: dict[str, Any]
) -> None:
    advice = payment_advice[expected["customer_id"]]
    assert advice.total_balance == Decimal(expected["total_balance"])
    assert advice.over_limit == expected["over_limit"]
    assert advice.max_days_overdue == expected["max_days_overdue"]
    # Policy 2.2 counts a bill as overdue from day 1; the key lists only the bills 7 or more
    # days overdue (the ones that trigger a reminder), so compare those.
    reminder_worthy = [b.bill_no for b in advice.overdue_bills if b.days_overdue >= 7]
    assert sorted(reminder_worthy) == sorted(expected["overdue_bills"])
