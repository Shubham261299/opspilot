from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.domain.credit import OpenBill, check_payment, days_overdue

TODAY = date(2026, 9, 24)
LIMIT = Decimal(50000)
CREDIT_DAYS = 15


def bill_overdue_by(days: int, balance: int = 10000, bill_no: str = "ST/1") -> OpenBill:
    return OpenBill(bill_no, TODAY - timedelta(days=CREDIT_DAYS + days), Decimal(balance))


def test_days_overdue_counts_from_the_end_of_the_credit_period() -> None:
    assert days_overdue(date(2026, 8, 17), 15, TODAY) == 23
    assert days_overdue(date(2026, 9, 20), 15, TODAY) == -11  # not due yet


@pytest.mark.parametrize(
    ("days", "action"),
    [
        (0, None),
        (6, None),
        (7, "SEND_REMINDER"),
        (30, "SEND_REMINDER"),
        (31, "HOLD_NEW_ORDERS"),  # "more than 30 days"
    ],
)
def test_action_depends_on_the_most_overdue_bill(days: int, action: str | None) -> None:
    advice = check_payment([bill_overdue_by(days)], LIMIT, CREDIT_DAYS, TODAY)
    assert advice.action == action


def test_balance_above_the_limit_means_hold_even_with_nothing_overdue() -> None:
    advice = check_payment([bill_overdue_by(-5, balance=50001)], LIMIT, CREDIT_DAYS, TODAY)
    assert (advice.action, advice.over_limit, advice.overdue_bills) == ("HOLD_NEW_ORDERS", True, ())


def test_balance_exactly_at_the_limit_is_not_over_it() -> None:
    advice = check_payment([bill_overdue_by(-5, balance=50000)], LIMIT, CREDIT_DAYS, TODAY)
    assert (advice.action, advice.over_limit) == (None, False)


def test_hold_wins_and_every_reason_is_listed() -> None:
    bills = [bill_overdue_by(40, 30000, "ST/1"), bill_overdue_by(10, 30000, "ST/2")]
    advice = check_payment(bills, LIMIT, CREDIT_DAYS, TODAY)
    assert advice.action == "HOLD_NEW_ORDERS"
    assert len(advice.reasons) == 2  # 40 days overdue, and ₹60,000 is above the limit
    assert [b.bill_no for b in advice.overdue_bills] == ["ST/1", "ST/2"]  # most overdue first
    assert (advice.total_balance, advice.max_days_overdue) == (Decimal(60000), 40)


def test_no_bills_no_action() -> None:
    advice = check_payment([], LIMIT, CREDIT_DAYS, TODAY)
    assert (advice.action, advice.total_balance, advice.max_days_overdue) == (None, 0, 0)
