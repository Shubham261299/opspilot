"""Checking that text written by the language model uses only numbers it was given.

CLAUDE.md rule 3: code calculates, the model explains. When the model words an explanation
or a reminder, every number in its text must already appear in the figures code computed.
A new number means it calculated, rounded or made something up, so the text is rejected.

Numbers are compared by value, the way people write them: "₹1,78,200", "178200" and
"178200.00" are the same; so are "08" and "8" (from a date like 2026-08-17).
"""

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[Decimal]:
    found = set()
    for token in _NUMBER.findall(text):
        try:
            found.add(Decimal(token.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return found


def unexpected_numbers(text: str, sources: Iterable[str]) -> list[str]:
    """Numbers in `text` that appear in none of `sources`, as written; [] means the text is fine."""
    allowed: set[Decimal] = set()
    for source in sources:
        allowed |= numbers_in(source)
    return sorted(
        token
        for token in set(_NUMBER.findall(text))
        if Decimal(token.replace(",", "")).normalize() not in allowed
    )
