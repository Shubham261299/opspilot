import pytest

from app.domain.text_numbers import unexpected_numbers

FIGURES = '{"qty": 110, "est_cost": "178200.00", "avg_daily": "3.40", "bill_date": "2026-08-17"}'


@pytest.mark.parametrize(
    "text",
    [
        "Order 110 coils for about ₹1,78,200.",  # Indian grouping of 178200.00
        "It sells 3.4 a day.",  # 3.40 written shorter
        "The bill of 17/08 is due.",  # parts of a date
        "No numbers at all.",
    ],
)
def test_numbers_that_were_given_are_allowed(text: str) -> None:
    assert unexpected_numbers(text, [FIGURES]) == []


@pytest.mark.parametrize(
    ("text", "unexpected"),
    [
        ("Order 120 coils.", ["120"]),  # a changed quantity
        ("About ₹1,78,000.", ["1,78,000"]),  # a rounded amount
        ("That is 1620 per coil.", ["1620"]),  # a new calculation
    ],
)
def test_new_numbers_are_caught(text: str, unexpected: list[str]) -> None:
    assert unexpected_numbers(text, [FIGURES]) == unexpected


def test_numbers_from_every_source_count() -> None:
    assert unexpected_numbers("5 days lead time, 110 coils", ["lead time 5", FIGURES]) == []
