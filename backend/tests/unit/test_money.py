from decimal import Decimal

import pytest

from app.domain.money import format_inr


@pytest.mark.parametrize(
    ("amount", "shown"),
    [
        (Decimal(0), "₹0"),
        (Decimal(950), "₹950"),
        (Decimal(1000), "₹1,000"),
        (Decimal(178200), "₹1,78,200"),
        (Decimal("2375000.5"), "₹23,75,000.50"),
        (Decimal(123456789), "₹12,34,56,789"),
        (Decimal(-5000), "-₹5,000"),
        (95, "₹95"),
    ],
)
def test_amounts_use_indian_grouping(amount: Decimal | int, shown: str) -> None:
    assert format_inr(amount) == shown
