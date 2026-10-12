"""Anomalies the owner must look at before anything goes ahead (company policy 3.1, 4.1, 4.2).

    order size     a line is MORE than 5x the customer's average quantity for that item
    price jump     an invoice rate is MORE than 10% above the last purchase rate
    duplicate      the same supplier sends the same invoice number again

Pure functions: the callers fetch the history (past sales, earlier invoices) and pass it in.
An anomaly never blocks or approves anything by itself; it is shown on the proposal so a
human decides with it in view.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class AnomalyPolicy:
    order_size_multiple: int = 5  # policy 3.1
    price_jump_percent: Decimal = Decimal(10)  # policy 4.1


DEFAULT_ANOMALY_POLICY = AnomalyPolicy()  # the company policy as written


# Order size (policy 3.1) ---------------------------------------------------------------------


@dataclass(frozen=True)
class OrderSizeAnomaly:
    qty: int
    usual_qty: Decimal  # the customer's average for this item, 1 decimal, for display
    times_usual: Decimal  # qty / usual, 1 decimal
    past_orders: int


def order_size_anomaly(
    qty: int, past_qtys: Sequence[int], policy: AnomalyPolicy = DEFAULT_ANOMALY_POLICY
) -> OrderSizeAnomaly | None:
    """`past_qtys`: the quantities on this customer's earlier sales lines for this item.
    No history means nothing to compare with, so no anomaly (a first order is normal)."""
    if not past_qtys:
        return None
    total = sum(past_qtys)
    # qty > multiple x (total / count), multiplied out to stay in whole numbers
    if qty * len(past_qtys) <= policy.order_size_multiple * total:
        return None
    usual = Decimal(total) / len(past_qtys)
    return OrderSizeAnomaly(
        qty=qty,
        usual_qty=_round(usual, "0.1"),
        times_usual=_round(Decimal(qty) / usual, "0.1"),
        past_orders=len(past_qtys),
    )


# Price jump (policy 4.1) ---------------------------------------------------------------------


@dataclass(frozen=True)
class PurchaseRate:
    rate: Decimal
    on: date | None  # the earlier invoice's date; None = the product master's cost price
    invoice_no: str | None


@dataclass(frozen=True)
class PriceJump:
    rate: Decimal
    last: PurchaseRate
    percent: Decimal  # rise over the last rate, 1 decimal


def last_purchase_rate(earlier: Iterable[PurchaseRate], cost_price: Decimal) -> PurchaseRate:
    """The rate on the most recent earlier invoice for the product; the product master's cost
    price when there is none (decision 035)."""
    dated = [rate for rate in earlier if rate.on is not None]
    if not dated:
        return PurchaseRate(cost_price, None, None)
    return max(dated, key=lambda rate: rate.on or date.min)


def price_jump(
    rate: Decimal, last: PurchaseRate, policy: AnomalyPolicy = DEFAULT_ANOMALY_POLICY
) -> PriceJump | None:
    if last.rate <= 0:
        return None
    # rate > last x (1 + p/100)  <=>  100 x rate > (100 + p) x last
    if 100 * rate <= (100 + policy.price_jump_percent) * last.rate:
        return None
    return PriceJump(rate, last, _round((rate - last.rate) * 100 / last.rate, "0.1"))


# Duplicate invoice (policy 4.2) --------------------------------------------------------------


@dataclass(frozen=True)
class EarlierInvoice:
    invoice_id: int
    supplier_code: str
    invoice_no: str


def invoice_key(invoice_no: str) -> str:
    """Invoice numbers compared the way people mean them: case, spaces and separators
    ignored ("SC-118", "sc 118" and "SC/118" are the same)."""
    return "".join(ch for ch in invoice_no.casefold() if ch.isalnum())


def duplicate_of(
    supplier_code: str | None, invoice_no: str, earlier: Iterable[EarlierInvoice]
) -> EarlierInvoice | None:
    """An earlier invoice from the same supplier with the same number, if any. Without a known
    supplier there is nothing to compare (it is reported as an unknown supplier instead)."""
    if supplier_code is None:
        return None
    key = invoice_key(invoice_no)
    for invoice in earlier:
        if invoice.supplier_code == supplier_code and invoice_key(invoice.invoice_no) == key:
            return invoice
    return None


def _round(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
