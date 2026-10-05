from datetime import date

import pytest

from app.domain.dates import find_date, infer_date, parse_day_first

REFERENCE = date(2026, 9, 24)


def test_day_and_month_without_year_use_the_reference_year() -> None:
    assert infer_date(22, 9, None, REFERENCE) == date(2026, 9, 22)


def test_the_reference_day_itself_counts() -> None:
    assert infer_date(24, 9, None, REFERENCE) == REFERENCE


def test_a_date_that_would_be_in_the_future_belongs_to_last_year() -> None:
    assert infer_date(28, 12, None, date(2027, 1, 5)) == date(2026, 12, 28)


@pytest.mark.parametrize(("year", "expected"), [(2025, date(2025, 3, 1)), (25, date(2025, 3, 1))])
def test_an_explicit_year_is_used_as_written(year: int, expected: date) -> None:
    assert infer_date(1, 3, year, REFERENCE) == expected


@pytest.mark.parametrize(("day", "month"), [(31, 2), (0, 5), (12, 13)])
def test_impossible_dates_return_none(day: int, month: int) -> None:
    assert infer_date(day, month, None, REFERENCE) is None


def test_29_february_goes_back_to_the_last_leap_year_if_needed() -> None:
    assert infer_date(29, 2, None, date(2025, 3, 1)) == date(2024, 2, 29)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Updated by Ravi on 24/9 evening (godown count)", date(2026, 9, 24)),
        ("count of 01-09-2026", date(2026, 9, 1)),
        ("stock as on 3.9.26", date(2026, 9, 3)),
        ("99/99 then 20/9", date(2026, 9, 20)),  # the first *valid* date wins
    ],
)
def test_find_date_reads_day_first_dates_in_text(text: str, expected: date) -> None:
    assert find_date(text, REFERENCE) == expected


@pytest.mark.parametrize("text", ["SHARMA TRADERS - STOCK REGISTER", "", "rate 1150"])
def test_find_date_returns_none_without_a_date(text: str) -> None:
    assert find_date(text, REFERENCE) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("15-08-2026", date(2026, 8, 15)),
        (" 15/8/26 ", date(2026, 8, 15)),
        ("15.08.2026", date(2026, 8, 15)),
        ("15/8", date(2026, 8, 15)),
    ],
)
def test_a_date_typed_as_text_is_read_day_first(text: str, expected: date) -> None:
    assert parse_day_first(text, REFERENCE) == expected


@pytest.mark.parametrize("text", ["31-02-2026", "on 15/8", "2026-08-15", "soon"])
def test_text_that_is_not_only_a_valid_date_is_not_a_date(text: str) -> None:
    assert parse_day_first(text, REFERENCE) is None
