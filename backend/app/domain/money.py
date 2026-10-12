"""Showing rupee amounts the Indian way: ₹1,78,200 (lakh and crore grouping)."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def format_inr(amount: Decimal | int) -> str:
    """Decimal("178200") -> "₹1,78,200"; Decimal("95.5") -> "₹95.50"; paise only when needed."""
    value = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if value < 0 else ""
    rupees, paise = f"{abs(value):.2f}".split(".")
    if len(rupees) > 3:
        head, tail = rupees[:-3], rupees[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        groups.insert(0, head)
        rupees = ",".join([*groups, tail])
    return f"{sign}₹{rupees}" + ("" if paise == "00" else f".{paise}")


def parse_amount(text: str | int | float | None) -> Decimal | None:
    """An amount as people write it ("1,620.00", "Rs 1,04,600.00", "₹ 63.36") -> Decimal.

    None when it isn't an amount."""
    if text is None or isinstance(text, bool):
        return None
    cleaned = re.sub(r"^\s*(₹|rs\.?|inr)\s*", "", str(text), flags=re.IGNORECASE)
    cleaned = cleaned.replace(",", "").strip()
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None
