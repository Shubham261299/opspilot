"""Prompts and schemas for explaining a proposal to the owner, and drafting a reminder.

The model only words things. It gets the figures code already computed and the template
reason, and must not add a number of its own; agents/approval.py checks that with
domain/text_numbers.py and falls back to the template when the check fails.
"""

import json
from typing import Any

from pydantic import BaseModel, Field

Message = dict[str, str]


class Explanation(BaseModel):
    explanation: str = Field(description="2 or 3 short sentences for the shop owner")


class ReminderDraft(Explanation):
    customer_message: str = Field(description="A polite WhatsApp message to the customer")


_KIND_TASKS = {
    "reorder": "a purchase order to a supplier",
    "payment_reminder": "a payment reminder to a customer",
    "hold_orders": "putting a customer's new orders on hold",
    "confirm_order": "confirming a customer's WhatsApp order",
}

_SYSTEM = """You help the owner of Sharma Traders, an electrical and hardware distributor in \
Pune, decide on a proposed action. Explain the proposal in 2 or 3 short sentences of simple \
English (a few Hindi words are fine): what it is, and the one or two figures that matter most.

Strict rules:
- Use ONLY numbers that appear in the figures or the reason you are given, written the same \
way or with Indian comma grouping (178200 can be written 1,78,200). Never calculate, round or \
estimate a new number.
- Don't decide for the owner and don't add facts that aren't given."""

_REMINDER = """
Also write customer_message: a short, polite WhatsApp payment reminder to the customer, in \
simple Hinglish or English (company policy 2.5). Greet them by name, mention their overdue \
bill numbers and amounts from the figures, and ask kindly for payment. Never threaten, and \
never mention any other customer."""


def explain_messages(
    kind: str, reason: str, numbers: dict[str, Any], customer_name: str | None
) -> list[Message]:
    system = _SYSTEM + (_REMINDER if kind == "payment_reminder" else "")
    facts = {
        "proposal": _KIND_TASKS.get(kind, kind),
        "customer": customer_name,
        "reason": reason,
        "figures": numbers,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False, indent=1)},
    ]


def schema_for(kind: str) -> type[Explanation]:
    return ReminderDraft if kind == "payment_reminder" else Explanation
