import pytest

from app.domain.units import CANONICAL_UNITS, normalise_unit


@pytest.mark.parametrize(
    ("spelling", "unit"),
    [
        # every spelling used in the sample stock register
        ("NOS", "piece"),
        ("nos", "piece"),
        ("Pcs", "piece"),
        ("pcs", "piece"),
        ("piece", "piece"),
        ("COIL", "coil"),
        ("Coil", "coil"),
        ("coils", "coil"),
        ("Roll", "roll"),
        ("Lgth", "length"),
        ("len", "length"),
        ("Pkt", "packet"),
        ("packet", "packet"),
        ("box", "box"),
        ("kg", "kg"),
        # extra forms
        ("Nos.", "piece"),
        ("  PCS  ", "piece"),
        ("boxes", "box"),
        ("Kgs", "kg"),
    ],
)
def test_known_spellings_map_to_the_standard_unit(spelling: str, unit: str) -> None:
    assert normalise_unit(spelling) == unit


@pytest.mark.parametrize("spelling", ["dozen", "mtr", "", "   ", None])
def test_unknown_or_blank_units_return_none(spelling: str | None) -> None:
    assert normalise_unit(spelling) is None


def test_every_standard_unit_maps_to_itself() -> None:
    assert {normalise_unit(unit) for unit in CANONICAL_UNITS} == CANONICAL_UNITS
