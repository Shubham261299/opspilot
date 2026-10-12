from datetime import date
from decimal import Decimal

import pytest

from app.domain.anomalies import (
    EarlierInvoice,
    PurchaseRate,
    duplicate_of,
    invoice_key,
    last_purchase_rate,
    order_size_anomaly,
    price_jump,
)

D = Decimal


# Order size --------------------------------------------------------------------------------


def test_exactly_five_times_the_usual_is_not_an_anomaly() -> None:
    assert order_size_anomaly(10, [2, 2]) is None  # usual 2, 10 = 5x: allowed


def test_more_than_five_times_the_usual_is() -> None:
    anomaly = order_size_anomaly(11, [2, 2])
    assert anomaly is not None
    assert (anomaly.usual_qty, anomaly.times_usual, anomaly.past_orders) == (D("2.0"), D("5.5"), 2)


def test_royal_hardwares_200_coils() -> None:
    anomaly = order_size_anomaly(200, [1, 2, 2])  # usual 1.67 coils
    assert anomaly is not None and (anomaly.usual_qty, anomaly.times_usual) == (
        D("1.7"),
        D("120.0"),
    )


def test_a_first_order_has_nothing_to_compare_with() -> None:
    assert order_size_anomaly(500, []) is None


# Price jump ---------------------------------------------------------------------------------

MASTER = PurchaseRate(D("48.00"), None, None)


def test_brightlines_9w_bulb_is_32_percent_up() -> None:
    jump = price_jump(D("63.36"), MASTER)
    assert jump is not None and jump.percent == D("32.0")


@pytest.mark.parametrize(("rate", "flagged"), [(D("52.80"), False), (D("52.81"), True)])
def test_the_limit_is_more_than_10_percent(rate: Decimal, flagged: bool) -> None:
    assert (price_jump(rate, MASTER) is not None) is flagged  # 52.80 = exactly +10%


def test_a_lower_or_equal_rate_is_fine() -> None:
    assert price_jump(D("48.00"), MASTER) is None
    assert price_jump(D("40.00"), MASTER) is None


def test_the_latest_earlier_invoice_beats_the_master_price() -> None:
    earlier = [
        PurchaseRate(D("50.00"), date(2026, 8, 1), "BL-0800"),
        PurchaseRate(D("60.00"), date(2026, 9, 1), "BL-0850"),
    ]
    last = last_purchase_rate(earlier, cost_price=D("48.00"))
    assert (last.rate, last.invoice_no) == (D("60.00"), "BL-0850")
    assert price_jump(D("63.36"), last) is None  # +5.6% on the last invoice: fine


def test_without_earlier_invoices_the_master_price_is_used() -> None:
    assert last_purchase_rate([], cost_price=D("48.00")) == MASTER


# Duplicate invoice ----------------------------------------------------------------------------

SC_118 = EarlierInvoice(1, "SUP04", "SC-118")


@pytest.mark.parametrize("written", ["SC-118", "sc 118", "SC/118", " SC-118 "])
def test_the_same_number_written_differently_is_a_duplicate(written: str) -> None:
    assert duplicate_of("SUP04", written, [SC_118]) == SC_118


def test_the_same_number_from_another_supplier_is_not() -> None:
    assert duplicate_of("SUP01", "SC-118", [SC_118]) is None


def test_an_unknown_supplier_is_not_compared() -> None:
    assert duplicate_of(None, "SC-118", [SC_118]) is None


def test_invoice_keys() -> None:
    assert invoice_key("KC/26-27/2291") == "kc26272291"
