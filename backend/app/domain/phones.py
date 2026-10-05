"""Indian mobile numbers, written many ways, stored one way: "+919895822412"."""

import re
from typing import Literal

PhoneStyle = Literal["plain", "dashes", "country code", "leading zero"]


def normalise_phone(raw: str | int | None) -> str | None:
    """'98958-22412', '+91 98892 54563', '09810872248', 9846913810 -> '+91XXXXXXXXXX'.

    Returns None when it isn't a valid Indian mobile number (10 digits starting 6-9).
    """
    if raw is None or isinstance(raw, bool):
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return None
    return f"+91{digits}"


def phone_style(raw: str | int) -> PhoneStyle:
    """How a valid number was written, for the "phone formats" issue."""
    text = str(raw).strip()
    if text.startswith("+") or (len(re.sub(r"\D", "", text)) == 12):
        return "country code"
    if text.startswith("0"):
        return "leading zero"
    if re.search(r"[\s-]", text):
        return "dashes"
    return "plain"
