"""Which policy rules a proposal follows. A fixed mapping, not a search (decision 044).

Every proposal is produced by code that applies particular rules of the company policy: the
reorder check applies 1.2 to 1.4, the credit check 2.3 or 2.4, and so on. So the rules to show
next to a proposal are known exactly, and are listed here. A similarity search could cite a
neighbouring rule on a card the owner relies on; this cannot. (Search is for the Policy page.)

The rule numbers are those of `company_policy.pdf`; a test checks that each one still exists in
the sample policy, so renumbering the policy cannot silently break the citations. The wording of
a rule is not kept here: it is looked up from the stored policy when the proposal is shown.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Citation:
    code: str  # the rule's number as printed in the policy, e.g. "2.4"
    why: str  # what this proposal did with that rule, in plain words


def citations_for(kind: str, numbers: Mapping[str, Any]) -> list[Citation]:
    """The rules applied to produce a proposal of this kind, from the figures it carries
    (`numbers`, as saved on the proposal). Unknown kinds follow no rule."""
    match kind:
        case "reorder":
            return _reorder(numbers)
        case "payment_reminder":
            return _reminder(numbers)
        case "hold_orders":
            return _hold(numbers)
        case "confirm_order":
            return _order(numbers)
        case "approve_invoice":
            return _invoice(numbers)
    return []


def _reorder(numbers: Mapping[str, Any]) -> list[Citation]:
    cited = [
        Citation("1.2", "The reorder point is average daily sales × lead time, plus safety stock"),
        Citation("1.3", "Stock on hand plus on order is at or below the reorder point"),
        Citation("1.4", "The quantity covers lead time plus 30 days, rounded up to the pack size"),
    ]
    if numbers.get("needs_owner"):
        cited.append(Citation("1.5", "A purchase order above ₹1,00,000 needs the owner's approval"))
    return cited


def _reminder(numbers: Mapping[str, Any]) -> list[Citation]:
    days = numbers.get("max_days_overdue")
    return [
        Citation("2.3", f"A bill is {days} days overdue; reminders start at 7"),
        Citation("2.5", "The message is polite and names no other customer"),
    ]


def _hold(numbers: Mapping[str, Any]) -> list[Citation]:
    days, over_limit = numbers.get("max_days_overdue"), numbers.get("over_limit")
    reasons = []
    if isinstance(days, int) and days > 30:
        reasons.append(f"a bill is {days} days overdue (more than 30)")
    if over_limit:
        reasons.append("the balance is above the credit limit")
    return [
        Citation("2.4", "New orders go on hold when " + " and ".join(reasons or ["it applies"]))
    ]


def _order(numbers: Mapping[str, Any]) -> list[Citation]:
    cited = []
    if numbers.get("customer_on_hold"):
        cited.append(Citation("2.4", "This customer is on hold, so dispatch needs the owner"))
    if numbers.get("unusually_large"):
        cited.append(Citation("3.1", "A quantity is more than 5× the customer's usual"))
    if numbers.get("unclear"):
        cited.append(Citation("3.2", "Part of a message is unclear, so ask the customer"))
    return cited


def _invoice(numbers: Mapping[str, Any]) -> list[Citation]:
    jumps = numbers.get("price_jumps") or 0
    price = (
        f"{jumps} rate{'s are' if jumps != 1 else ' is'} more than 10% above the last purchase rate"
        if jumps
        else "Every rate is within 10% of the last purchase rate"
    )
    return [
        Citation("4.1", price),
        Citation("4.2", "No earlier invoice with this number from this supplier was found"),
    ]
