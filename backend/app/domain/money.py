"""Showing rupee amounts the Indian way: ₹1,78,200 (lakh and crore grouping)."""

from decimal import ROUND_HALF_UP, Decimal


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
