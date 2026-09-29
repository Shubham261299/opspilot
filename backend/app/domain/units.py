"""Units of measure: the many ways people write them, mapped to one standard spelling."""

# The units used in the product master.
CANONICAL_UNITS = frozenset({"piece", "coil", "roll", "length", "packet", "box", "kg"})

_SPELLINGS = {
    "piece": ("piece", "pieces", "pc", "pcs", "nos", "no", "number", "numbers", "ea", "each"),
    "coil": ("coil", "coils"),
    "roll": ("roll", "rolls"),
    "length": ("length", "lengths", "len", "lgth", "lth"),
    "packet": ("packet", "packets", "pkt", "pkts", "pack", "packs"),
    "box": ("box", "boxes", "bx"),
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"),
}
_UNIT_BY_SPELLING = {
    spelling: unit for unit, spellings in _SPELLINGS.items() for spelling in spellings
}


def normalise_unit(raw: str | None) -> str | None:
    """Return the standard unit for a spelling ("NOS" -> "piece"), or None if unknown or blank."""
    if raw is None:
        return None
    return _UNIT_BY_SPELLING.get(raw.strip().lower().rstrip("."))
