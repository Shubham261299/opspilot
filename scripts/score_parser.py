"""Score the WhatsApp order parser against sample_data/answer_key.json, with the real model.

    python scripts/score_parser.py                        (uses LLM_MODEL, default qwen2.5:7b)
    LLM_MODEL=ollama_chat/qwen2.5:14b python scripts/score_parser.py

Runs the same code the app runs (intake/whatsapp.py + intake/whatsapp_orders.py + app/llm)
on sample_data/whatsapp_orders_export.txt and compares every order line with the answer key.
The answer key is read only here, never by the app. Results are printed and saved to
scripts/results/, so numbers quoted in the README come from an actual run.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused/unused")  # no DB needed

from app.config import get_settings  # noqa: E402
from app.db.seed import ProductRow, SupplierRow, read_csv_rows  # noqa: E402
from app.domain.catalog import Catalog, CatalogProduct, CatalogSupplier  # noqa: E402
from app.intake.customers import parse_customers  # noqa: E402
from app.intake.whatsapp import parse_chat  # noqa: E402
from app.intake.whatsapp_orders import read_whatsapp_orders  # noqa: E402

DATA = ROOT / "sample_data"


def load_catalog() -> Catalog:
    suppliers = read_csv_rows(DATA / "suppliers.csv", SupplierRow)
    products = read_csv_rows(DATA / "product_master.csv", ProductRow)
    return Catalog.build(
        products=[
            CatalogProduct(
                sku=p.sku,
                name=p.name,
                aliases=tuple(p.aliases),
                unit=p.unit,
                cost_price=p.cost_price,
                sell_price=p.sell_price,
                supplier_code=p.supplier_code,
            )
            for p in products
        ],
        suppliers=[CatalogSupplier(code=s.code, name=s.name) for s in suppliers],
    )


async def main() -> None:
    key = json.loads((DATA / "answer_key.json").read_text(encoding="utf-8"))
    customers = parse_customers((DATA / "customers.xlsx").read_bytes()).customers
    chat = parse_chat(
        (DATA / "whatsapp_orders_export.txt").read_text(encoding="utf-8"), "Sharma Traders"
    )
    model = get_settings().llm_model
    print(f"Reading {len(chat.threads)} threads with {model} ...", flush=True)
    reading = await read_whatsapp_orders(
        chat, load_catalog(), {c.code: c.shop_name for c in customers}
    )

    expected = {
        o["customer"]: {(i["sku"], i["qty"]) for i in o["items"]} for o in key["expected_orders"]
    }
    actual = {o.sender: o for o in reading.orders}
    rows, totals = [], {"exact": 0, "wrong_qty": 0, "missing": 0, "extra": 0, "unmatched": 0}
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
        ok = len(exact) == len(want) and not extra and not unmatched
        rows.append(
            {
                "customer": customer,
                "all_right": ok,
                "exact": len(exact),
                "expected": len(want),
                "wrong_qty": sorted(wrong_qty),
                "missing": sorted(missing),
                "extra": sorted(extra),
                "unmatched": unmatched,
            }
        )
        print(
            f"{'OK ' if ok else '-- '} {customer:28} {len(exact)}/{len(want)} lines"
            + (f"  wrong qty {sorted(wrong_qty)}" if wrong_qty else "")
            + (f"  missing {sorted(missing)}" if missing else "")
            + (f"  extra {sorted(extra)}" if extra else "")
            + (f"  unmatched {unmatched}" if unmatched else "")
        )

    non_orders = [n["from_"] for n in key["non_orders"]]
    # A non-order is a message, not a customer: Mahalaxmi Traders also placed a real order, so
    # their payment promise only counts as wrong if it added lines (those show up as "extra").
    false_orders = [s for s in non_orders if s not in expected and s in actual and actual[s].lines]
    surprise_orders = [s for s in actual if s not in expected and s not in non_orders]
    lines_expected = sum(len(v) for v in expected.values())
    summary = {
        "model": model,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": round(reading.seconds),
        "model_calls": reading.model_calls,
        "orders_fully_right": sum(r["all_right"] for r in rows),
        "orders_expected": len(expected),
        "lines_exact": totals["exact"],
        "lines_expected": lines_expected,
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
    print("\n" + json.dumps(summary, indent=2))
    out = ROOT / "scripts" / "results"
    out.mkdir(exist_ok=True)
    name = model.split("/")[-1].replace(":", "-")
    (out / f"score_parser_{name}.json").write_text(
        json.dumps({"summary": summary, "orders": rows}, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
