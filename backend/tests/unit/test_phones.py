import pytest

from app.domain.phones import normalise_phone, phone_style


@pytest.mark.parametrize(
    ("raw", "style"),
    [
        ("9895822412", "plain"),
        (9895822412, "plain"),
        ("98958-22412", "dashes"),
        ("98958 22412", "dashes"),
        ("+91 98958 22412", "country code"),
        ("919895822412", "country code"),
        ("09895822412", "leading zero"),
    ],
)
def test_every_way_of_writing_a_mobile_gives_the_same_number(raw: str | int, style: str) -> None:
    assert normalise_phone(raw) == "+919895822412"
    assert phone_style(raw) == style


@pytest.mark.parametrize(
    "raw", [None, "", "12345", "989582241", "5895822412", "98958224121", "call me", True]
)
def test_anything_else_is_not_a_mobile(raw: str | int | None) -> None:
    assert normalise_phone(raw) is None
