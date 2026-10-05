"""Reading any messy Excel workbook into rows that keep their real row numbers.

pandas loads each sheet as a raw grid:
- header=None: don't assume where the header is (title rows often come first)
- dtype=object: keep every cell as typed, so "54 pcs" stays text and 54 stays a number
- keep_default_na=False: only empty cells are blank; text like "n/a" or "NA" is kept,
  so it can be reported instead of silently vanishing
Row n of the grid is Excel row n + 1. What each row *means* is decided by the
file-specific modules (e.g. stock_register.py).
"""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

import pandas as pd
from openpyxl.utils import get_column_letter

from app.intake.errors import IntakeError


@dataclass(frozen=True)
class SheetRow:
    number: int  # the row number Excel shows, starting at 1
    values: tuple[Any, ...]  # cleaned cell values (text trimmed); None means blank
    original: tuple[Any, ...]  # the same cells exactly as typed, e.g. "  gi box 8  "

    def is_blank(self) -> bool:
        return all(value is None for value in self.values)

    def filled(self) -> list[tuple[int, Any]]:
        """(column index, value) for every non-blank cell."""
        return [(col, value) for col, value in enumerate(self.values) if value is not None]

    def text(self) -> str:
        """All non-blank cells joined, for messages: "TOTAL ITEMS | 62"."""
        return " | ".join(str(value) for _, value in self.filled())


@dataclass(frozen=True)
class Sheet:
    name: str
    rows: tuple[SheetRow, ...]


@dataclass(frozen=True)
class Header:
    row_number: int
    columns: dict[str, int]  # field name -> column index
    labels: dict[int, str]  # column index -> the header text as written


def as_typed(value: Any) -> Any:
    """The cell exactly as typed, with pandas' markers for an empty cell turned into None."""
    if value is None or value is pd.NaT or (isinstance(value, str) and value == ""):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def clean_cell(value: Any) -> Any:
    """Like as_typed, but text is trimmed and whitespace-only text counts as blank."""
    value = as_typed(value)
    if isinstance(value, str):
        return value.strip() or None
    return value


def json_safe(value: Any) -> Any:
    """A cell value that can be stored as JSON (dates become ISO text)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return str(value)


def column_letter(col: int) -> str:
    return get_column_letter(col + 1)  # column index 0 -> "A"


def raw_cells(header: Header, row: SheetRow) -> dict[str, Any]:
    """The row's non-blank cells exactly as typed, keyed by column title (for issue records)."""
    return {
        header.labels.get(col, column_letter(col)): json_safe(row.original[col])
        for col, _ in row.filled()
    }


def cells_by_field(header: Header, row: SheetRow) -> dict[str, Any]:
    """The row's cleaned values by field name ("qty", "code", ...)."""
    return {
        field: row.values[col] for field, col in header.columns.items() if col < len(row.values)
    }


def parse_money(value: Any) -> Decimal | None:
    """1150, "1,150", "₹ 1150", "Rs. 1150" -> Decimal("1150"); anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return Decimal(str(value))
    text = re.sub(r"^(₹|rs\.?|inr)\s*", "", str(value), flags=re.IGNORECASE).replace(",", "")
    try:
        amount = Decimal(text.strip())
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def rupees(amount: Decimal) -> str:
    """Decimal("6500") -> "₹6500.00"."""
    return f"₹{amount.quantize(Decimal('0.01'))}"


def read_workbook(content: bytes) -> list[Sheet]:
    try:
        frames = pd.read_excel(
            BytesIO(content),
            sheet_name=None,
            header=None,
            dtype=object,
            keep_default_na=False,
            engine="openpyxl",
        )
    except Exception as exc:  # a bad file can fail in many ways inside pandas/openpyxl
        raise IntakeError(
            "unreadable_file", "The file could not be read as an Excel workbook (.xlsx)."
        ) from exc
    return [
        Sheet(
            name=str(name),
            rows=tuple(
                SheetRow(
                    number=index + 1,
                    values=tuple(clean_cell(value) for value in values),
                    original=tuple(as_typed(value) for value in values),
                )
                for index, values in enumerate(frame.itertuples(index=False, name=None))
            ),
        )
        for name, frame in frames.items()
    ]


def normalise_label(text: str) -> str:
    """Compare column titles loosely: "Rate (Purchase)" -> "rate purchase"."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


def find_header(
    sheet: Sheet,
    synonyms: Mapping[str, Sequence[str]],
    required: Sequence[str],
    any_of: Sequence[str],
    scan_rows: int = 30,
) -> Header | None:
    """Find the header: the first row whose cells name all `required` fields and one of `any_of`.

    `synonyms` maps each field to the column titles that mean it, for example
    "qty": ("qty in stock", "quantity"). Titles are compared with normalise_label.
    """
    for row in sheet.rows[:scan_rows]:
        columns: dict[str, int] = {}
        for col, value in row.filled():
            if not isinstance(value, str):
                continue
            label = normalise_label(value)
            for field, names in synonyms.items():
                if field not in columns and label in names:
                    columns[field] = col
                    break
        if all(field in columns for field in required) and any(f in columns for f in any_of):
            labels = {col: str(value) for col, value in row.filled()}
            return Header(row_number=row.number, columns=columns, labels=labels)
    return None
