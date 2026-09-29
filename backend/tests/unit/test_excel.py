from collections.abc import Callable
from datetime import datetime

import pytest

from app.intake.errors import IntakeError
from app.intake.excel import clean_cell, find_header, json_safe, normalise_label, read_workbook

SYNONYMS = {"name": ("item name", "item"), "qty": ("qty in stock", "qty")}


def test_rows_keep_their_real_excel_row_numbers(make_xlsx: Callable[..., bytes]) -> None:
    content = make_xlsx(
        [[], [], [None, "Item Name", "Qty"], [None, "Widget", "7 pcs"], [], [None, "Gadget", 5]]
    )

    (sheet,) = read_workbook(content)

    assert [row.number for row in sheet.rows] == [1, 2, 3, 4, 5, 6]
    assert sheet.rows[3].values == (None, "Widget", "7 pcs")  # text stays text
    assert sheet.rows[5].values == (None, "Gadget", 5)  # numbers stay numbers
    assert sheet.rows[4].is_blank()


def test_cells_are_kept_both_cleaned_and_exactly_as_typed(
    make_xlsx: Callable[..., bytes],
) -> None:
    (sheet,) = read_workbook(make_xlsx([["  gi box 8  ", "   ", 34]]))

    row = sheet.rows[0]
    assert row.values == ("gi box 8", None, 34)
    assert row.original == ("  gi box 8  ", "   ", 34)


def test_text_that_looks_like_missing_is_kept_as_text(make_xlsx: Callable[..., bytes]) -> None:
    # pandas would turn these into blanks by default, hiding them from the issue checks
    (sheet,) = read_workbook(make_xlsx([["n/a", "NA", "null", "None", "-"]]))

    assert sheet.rows[0].values == ("n/a", "NA", "null", "None", "-")


def test_every_sheet_is_read_in_order(make_xlsx: Callable[..., bytes]) -> None:
    content = make_xlsx([["a"]], other_sheets={"Notes": [["note one"]]})

    assert [sheet.name for sheet in read_workbook(content)] == ["Stock", "Notes"]


def test_a_file_that_is_not_excel_is_rejected() -> None:
    with pytest.raises(IntakeError) as error:
        read_workbook(b"Item,Qty\nWidget,5\n")
    assert error.value.code == "unreadable_file"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (float("nan"), None), ("  text  ", "text"), ("   ", None), (54, 54), (2.5, 2.5)],
)
def test_clean_cell(value: object, expected: object) -> None:
    assert clean_cell(value) == expected


def test_json_safe_turns_dates_into_text() -> None:
    assert json_safe(datetime(2026, 9, 24, 18, 30)) == "2026-09-24T18:30:00"
    assert json_safe(54) == 54


@pytest.mark.parametrize(
    ("title", "label"),
    [
        ("Rate (Purchase)", "rate purchase"),
        ("MRP / Sale Rate", "mrp sale rate"),
        (" Qty In Stock ", "qty in stock"),
    ],
)
def test_normalise_label(title: str, label: str) -> None:
    assert normalise_label(title) == label


def test_find_header_skips_title_rows_and_maps_columns(make_xlsx: Callable[..., bytes]) -> None:
    content = make_xlsx(
        [["MY SHOP - STOCK"], [], ["Qty", "Remarks", "Item"], ["5", None, "Widget"]]
    )
    (sheet,) = read_workbook(content)

    header = find_header(sheet, SYNONYMS, required=("qty",), any_of=("name",))

    assert header is not None
    assert header.row_number == 3
    assert header.columns == {"qty": 0, "name": 2}
    assert header.labels == {0: "Qty", 1: "Remarks", 2: "Item"}


def test_find_header_returns_none_without_the_required_columns(
    make_xlsx: Callable[..., bytes],
) -> None:
    (sheet,) = read_workbook(make_xlsx([["Item", "Price"], ["Widget", 10]]))

    assert find_header(sheet, SYNONYMS, required=("qty",), any_of=("name",)) is None
