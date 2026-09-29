"""Dates written the Indian way: day first, often without a year ("24/9")."""

import re
from datetime import date

# 24/9, 24-09-2026, 24.9.26 (day, month, optional year)
_DAY_FIRST_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{4}|\d{2}))?\b")


def infer_date(day: int, month: int, year: int | None, reference: date) -> date | None:
    """Build a date; a missing year means the latest such date on or before `reference`.

    With reference 5 Jan 2027, "28/12" is 28 Dec 2026, not 28 Dec 2027.
    Returns None for impossible dates such as 31/2.
    """
    if year is not None:
        full_year = year + 2000 if year < 100 else year
        try:
            return date(full_year, month, day)
        except ValueError:
            return None
    for candidate_year in (reference.year, reference.year - 1):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue  # e.g. 29/2 in a year that isn't a leap year
        if candidate <= reference:
            return candidate
    return None


def find_date(text: str, reference: date) -> date | None:
    """The first valid day-first date in `text` ("Updated on 24/9 evening" -> 24 Sep)."""
    for match in _DAY_FIRST_DATE.finditer(text):
        day, month, year = match.groups()
        found = infer_date(int(day), int(month), int(year) if year else None, reference)
        if found is not None:
            return found
    return None
