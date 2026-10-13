"""Eval: WhatsApp order reading, scored against the answer key.

Runs the same code the app runs (intake/whatsapp.py + intake/whatsapp_orders.py) on
sample_data/whatsapp_orders_export.txt and compares every order line with the key.
"""

from typing import Any

from app.intake.customers import parse_customers
from app.intake.whatsapp import parse_chat
from app.intake.whatsapp_orders import OrdersReading, read_whatsapp_orders
from evals.common import DATA, CountingAsk, Report, load_answer_key, load_catalog

SUITE = "whatsapp"


async def run(ask: CountingAsk) -> Report:
    key = load_answer_key()
    customers = parse_customers((DATA / "customers.xlsx").read_bytes()).customers
    chat = parse_chat(
        (DATA / "whatsapp_orders_export.txt").read_text(encoding="utf-8"), "Sharma Traders"
    )
    reading = await read_whatsapp_orders(
        chat, load_catalog(), {c.code: c.shop_name for c in customers}, ask
    )
    return score(key, reading, ask.calls)


def score(key: dict[str, Any], reading: OrdersReading, model_calls: int) -> Report:
    expected = {
        o["customer"]: {(i["sku"], i["qty"]) for i in o["items"]} for o in key["expected_orders"]
    }
    actual = {o.sender: o for o in reading.orders}
    rows: list[dict[str, Any]] = []
    totals = {"exact": 0, "wrong_qty": 0, "missing": 0, "extra": 0, "unmatched": 0}
    for customer, want in expected.items():
        order = actual.get(customer)
        got = {(line.sku, line.qty) for line in order.lines if line.sku} if order else set()
        unmatched = [line.written for line in order.lines if not line.sku] if order else []
        want_skus, got_skus = {s for s, _ in want}, {s for s, _ in got}
        exact = want & got
        wrong_qty = {s for s, _ in want - exact} & got_skus
        missing = want_skus - got_skus
        extra = got_skus - want_skus
        totals["exact"] += len(exact)
        totals["wrong_qty"] += len(wrong_qty)
        totals["missing"] += len(missing)
        totals["extra"] += len(extra)
        totals["unmatched"] += len(unmatched)
        rows.append(
            {
                "customer": customer,
                "all_right": len(exact) == len(want) and not extra and not unmatched,
                "exact": len(exact),
                "expected": len(want),
                "wrong_qty": sorted(wrong_qty),
                "missing": sorted(missing),
                "extra": sorted(extra),
                "unmatched": unmatched,
            }
        )

    non_orders = [n["from_"] for n in key["non_orders"]]
    # A non-order is a message, not a customer: Mahalaxmi Traders also placed a real order, so
    # their payment promise only counts as wrong if it added lines (those show up as "extra").
    false_orders = [s for s in non_orders if s not in expected and s in actual and actual[s].lines]
    surprise_orders = [s for s in actual if s not in expected and s not in non_orders]
    summary = {
        "model_calls": model_calls,
        "orders_fully_right": sum(r["all_right"] for r in rows),
        "orders_expected": len(expected),
        "lines_exact": totals["exact"],
        "lines_expected": sum(len(v) for v in expected.values()),
        "lines_wrong_qty": totals["wrong_qty"],
        "lines_missing": totals["missing"],
        "lines_extra": totals["extra"],
        "lines_sent_to_review": totals["unmatched"],
        "non_orders_right": len(non_orders) - len(false_orders),
        "non_orders_expected": len(non_orders),
        "orders_for_unexpected_senders": surprise_orders,
        "issues_by_type": {
            t: sum(1 for i in reading.issues if i.issue_type.value == t)
            for t in sorted({i.issue_type.value for i in reading.issues})
        },
    }
    return Report(summary, rows)
