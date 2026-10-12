"""Score the anomaly rules against sample_data/answer_key.json, on the real files.

The answer key is used ONLY in tests. Its expected orders stand in for the WhatsApp parser
here, so this measures the rules alone; the invoices come from the real PDFs (text and table
rows read by code, no model needed).
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from app.domain.anomalies import (
    EarlierInvoice,
    duplicate_of,
    last_purchase_rate,
    order_size_anomaly,
    price_jump,
)
from app.domain.catalog import Catalog
from app.domain.matching import match_product_by_words, resolve_supplier
from app.intake.customers import parse_customers
from app.intake.invoice_pdf import pdf_text
from app.intake.invoices import rows_from_table
from app.intake.sales_history import parse_sales_history

ANSWER_KEY = json.loads(
    (Path(__file__).resolve().parents[3] / "sample_data" / "answer_key.json").read_text(
        encoding="utf-8"
    )
)
EXPECTED = {a["type"] for a in ANSWER_KEY["anomalies"]}


@pytest.fixture(scope="module")
def found(sample_data_dir: Path, catalog: Catalog) -> dict[str, list[tuple[str, ...]]]:
    """Every anomaly the rules raise, by type, as (who, what) pairs."""
    anomalies: dict[str, list[tuple[str, ...]]] = defaultdict(list)

    customers = parse_customers((sample_data_dir / "customers.xlsx").read_bytes()).customers
    code_of = {c.shop_name: c.code for c in customers}
    sales = parse_sales_history(
        (sample_data_dir / "sales_history_90d.csv").read_bytes(),
        set(code_of.values()),
        set(catalog.products),
    )
    past: dict[tuple[str, str], list[int]] = defaultdict(list)
    for sale in sales.sales:
        past[(sale.customer_code, sale.sku)].append(sale.qty)
    for order in ANSWER_KEY["expected_orders"]:
        code = code_of[order["customer"]]
        for item in order["items"]:
            if order_size_anomaly(item["qty"], past[(code, item["sku"])]):
                anomalies["order_size"].append((order["customer"], item["sku"]))

    earlier: list[EarlierInvoice] = []
    for number, path in enumerate(sorted(sample_data_dir.glob("invoice_*.pdf")), start=1):
        text = pdf_text(path.read_bytes())
        supplier = resolve_supplier(text.splitlines()[0], catalog)
        invoice_no = re.search(r"Invoice No:\s*(\S+)", text).group(1)  # type: ignore[union-attr]
        assert supplier is not None
        if duplicate_of(supplier.code, invoice_no, earlier):
            anomalies["duplicate_invoice"].append((supplier.code, invoice_no))
        earlier.append(EarlierInvoice(number, supplier.code, invoice_no))
        for _, description, _, rate, _ in rows_from_table(text):
            match = match_product_by_words(description, catalog)
            if match is None:
                continue  # matched by the model in the app; the 3 unmatched here are conduits
            product = catalog.products[match.sku]
            if price_jump(rate, last_purchase_rate([], product.cost_price)):
                anomalies["invoice_price_jump"].append((invoice_no, match.sku))
    return anomalies


def test_the_answer_key_lists_three_anomalies() -> None:
    assert {"order_size", "invoice_price_jump", "duplicate_invoice"} == EXPECTED


def test_royal_hardwares_order_is_found(found: dict[str, Any]) -> None:
    assert ("Royal Hardware", "ST-0003") in found["order_size"]


def test_the_policy_as_written_also_flags_bulk_orders(found: dict[str, Any]) -> None:
    # Measured, not a goal: the sample's sales history is counter-sized (1-10 units a line),
    # while WhatsApp orders are bulk, so "more than 5x the average sale" catches 27 more lines
    # (New Light House's 300 bulbs is 87x). No threshold catches only Royal (120x) without
    # fitting the answer key. Pinned here so any change to the rule shows up.
    assert len(found["order_size"]) == 28


def test_brightlines_9w_bulb_and_nothing_else(found: dict[str, Any]) -> None:
    assert found["invoice_price_jump"] == [("BL-0874", "ST-0017")]


def test_sai_conduits_sc_118_is_the_duplicate(found: dict[str, Any]) -> None:
    assert found["duplicate_invoice"] == [("SUP04", "SC-118")]
