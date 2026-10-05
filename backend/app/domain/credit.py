"""Customer credit: overdue bills, reminders and holds (company policy, section 2).

    a bill is overdue  when it is unpaid after the customer's credit days
    remind             when any bill is 7 or more days overdue
    hold new orders    when any bill is MORE than 30 days overdue,
                       or the total outstanding is above the credit limit

A customer gets at most one action. A hold is the stronger one, so it wins.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from app.domain.money import format_inr

PaymentAction = Literal["SEND_REMINDER", "HOLD_NEW_ORDERS"]


@dataclass(frozen=True)
class CreditPolicy:
    remind_at_days: int = 7  # remind when a bill is this many days overdue, or more
    hold_after_days: int = 30  # hold when a bill is more than this many days overdue


DEFAULT_CREDIT_POLICY = CreditPolicy()  # the company policy as written


@dataclass(frozen=True)
class OpenBill:
    bill_no: str
    bill_date: date
    balance: Decimal


@dataclass(frozen=True)
class OverdueBill:
    bill_no: str
    bill_date: date
    balance: Decimal
    days_overdue: int


@dataclass(frozen=True)
class PaymentAdvice:
    action: PaymentAction | None
    total_balance: Decimal
    credit_limit: Decimal
    over_limit: bool
    overdue_bills: tuple[OverdueBill, ...]  # most overdue first
    max_days_overdue: int  # 0 when nothing is overdue
    reasons: tuple[str, ...]  # which rules apply, in plain words


def days_overdue(bill_date: date, credit_days: int, today: date) -> int:
    """Days past the due date (bill date + credit days); 0 or less means not overdue yet."""
    return (today - bill_date).days - credit_days


def check_payment(
    bills: Iterable[OpenBill],
    credit_limit: Decimal,
    credit_days: int,
    today: date,
    policy: CreditPolicy = DEFAULT_CREDIT_POLICY,
) -> PaymentAdvice:
    bills = list(bills)
    total = sum((bill.balance for bill in bills), start=Decimal(0))
    overdue = sorted(
        (
            OverdueBill(bill.bill_no, bill.bill_date, bill.balance, days)
            for bill in bills
            if (days := days_overdue(bill.bill_date, credit_days, today)) > 0
        ),
        key=lambda bill: (-bill.days_overdue, bill.bill_no),
    )
    worst = overdue[0].days_overdue if overdue else 0
    over_limit = total > credit_limit

    reasons: list[str] = []
    if worst > policy.hold_after_days:
        reasons.append(f"a bill is {worst} days overdue (more than {policy.hold_after_days})")
    if over_limit:
        reasons.append(
            f"outstanding {format_inr(total)} is above the credit limit {format_inr(credit_limit)}"
        )
    action: PaymentAction | None = None
    if reasons:
        action = "HOLD_NEW_ORDERS"
    elif worst >= policy.remind_at_days:
        action = "SEND_REMINDER"
        reasons.append(f"a bill is {worst} days overdue ({policy.remind_at_days} or more)")
    return PaymentAdvice(
        action=action,
        total_balance=total,
        credit_limit=credit_limit,
        over_limit=over_limit,
        overdue_bills=tuple(overdue),
        max_days_overdue=worst,
        reasons=tuple(reasons),
    )
