from collections.abc import Callable
from io import BytesIO
from typing import Any

import openpyxl
import pytest

Rows = list[list[Any]]


def _make_xlsx(rows: Rows, other_sheets: dict[str, Rows] | None = None) -> bytes:
    """Build a small .xlsx in memory. `rows` go on the first sheet, starting at row 1;
    an empty list makes an empty row."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Stock"
    for row in rows:
        sheet.append(row)
    for name, extra_rows in (other_sheets or {}).items():
        extra = workbook.create_sheet(name)
        for row in extra_rows:
            extra.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def make_xlsx() -> Callable[..., bytes]:
    return _make_xlsx
