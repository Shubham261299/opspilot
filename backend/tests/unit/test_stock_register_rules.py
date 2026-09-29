"""Rules the sample file doesn't exercise, each checked on a small workbook built in the test."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.domain.catalog import Catalog, CatalogProduct, CatalogSupplier
from app.intake.errors import IntakeError
from app.intake.issues import IssueRecord, IssueType
from app.intake.stock_register import PoNote, StockRegisterResult, parse_stock_register

CATALOG = Catalog.build(
    products=[
        CatalogProduct(
            "ST-0001",
            "FR PVC Wire 1.0 sqmm 90m",
            ("1mm wire",),
            "coil",
            Decimal("1150"),
            Decimal("1390"),
            "SUP01",
        ),
        CatalogProduct(
            "ST-0009",
            "MCB 6A Single Pole",
            ("6a mcb",),
            "piece",
            Decimal("118"),
            Decimal("165"),
            "SUP02",
        ),
    ],
    suppliers=[
        CatalogSupplier("SUP01", "Kiran Cables Pvt Ltd"),
        CatalogSupplier("SUP02", "Volta Switchgear"),
        CatalogSupplier("SUP07", "Volta Lighting"),  # makes the short name "Volta" ambiguous
    ],
)
TODAY = date(2026, 9, 29)
TITLE = ["Stock count 24/9"]
HEADER = [
    "Item Code",
    "Item Name",
    "Unit",
    "Qty In Stock",
    "Rate (Purchase)",
    "MRP / Sale Rate",
    "Supplier",
    "Remarks",
]


def item(sku: str, **changes: Any) -> list[Any]:
    """A clean row for `sku`. Change any cell: item("ST-0001", qty=-2, unit="box")."""
    product = CATALOG.products[sku]
    cells = {
        "code": sku,
        "name": product.name,
        "unit": product.unit,
        "qty": 10,
        "purchase": int(product.cost_price),
        "sale": int(product.sell_price),
        "supplier": CATALOG.suppliers[product.supplier_code].name,
        "remarks": None,
    }
    cells.update(changes)
    return list(cells.values())


@pytest.fixture
def parse(make_xlsx: Callable[..., bytes]) -> Callable[..., StockRegisterResult]:
    def _parse(
        *rows: list[Any], other_sheets: dict[str, Any] | None = None, today: date = TODAY
    ) -> StockRegisterResult:
        return parse_stock_register(make_xlsx(list(rows), other_sheets), CATALOG, today)

    return _parse


Parse = Callable[..., StockRegisterResult]


def of_type(result: StockRegisterResult, issue_type: IssueType) -> list[IssueRecord]:
    return [i for i in result.issues if i.issue_type == issue_type]


def loaded(result: StockRegisterResult) -> dict[str, int]:
    return {row.sku: row.qty_on_hand for row in result.stock_rows}


# --- Finding the table ---


def test_a_clean_sheet_only_reports_its_title_row(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001"), item("ST-0009"))

    assert loaded(result) == {"ST-0001": 10, "ST-0009": 10}
    assert result.as_of == date(2026, 9, 24)
    assert [i.issue_type for i in result.issues] == [IssueType.SKIPPED_ROW]


def test_header_in_row_one_with_other_columns_in_any_order(parse: Parse) -> None:
    result = parse(["Qty", "Item Name"], [5, "MCB 6A Single Pole"], [3, "FR PVC Wire 1.0 sqmm 90m"])

    assert result.header_row == 1
    assert loaded(result) == {"ST-0009": 5, "ST-0001": 3}
    # no code or unit column: identified by name, counted in master units, no per-row noise
    assert [i.issue_type for i in result.issues] == [IssueType.COUNT_DATE_MISSING]
    assert result.as_of == TODAY


def test_header_after_blank_rows(parse: Parse) -> None:
    result = parse([], [], HEADER, item("ST-0001"), item("ST-0009"))

    assert result.header_row == 3
    assert loaded(result) == {"ST-0001": 10, "ST-0009": 10}


def test_a_sheet_without_a_header_row_is_rejected(parse: Parse) -> None:
    with pytest.raises(IntakeError) as error:
        parse(["Item", "Price"], ["Widget", 10])
    assert error.value.code == "header_not_found"


def test_a_file_that_is_not_excel_is_rejected() -> None:
    with pytest.raises(IntakeError) as error:
        parse_stock_register(b"not an excel file", CATALOG, TODAY)
    assert error.value.code == "unreadable_file"


# --- Which product ---


def test_unknown_item_code_is_rejected(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001", code="ST-0999"), item("ST-0009"))

    (issue,) = of_type(result, IssueType.UNKNOWN_ITEM)
    assert (issue.source_row, issue.severity) == (3, "error")
    assert loaded(result) == {"ST-0009": 10}
    (missing,) = of_type(result, IssueType.MISSING_FROM_REGISTER)
    assert missing.sku == "ST-0001"


def test_code_and_name_that_disagree_are_not_loaded(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001", name="MCB 6A Single Pole"), item("ST-0009"))

    (issue,) = of_type(result, IssueType.CODE_NAME_MISMATCH)
    assert issue.sku == "ST-0001"
    assert "ST-0001" not in loaded(result)
    assert not of_type(result, IssueType.MISSING_FROM_REGISTER)  # it *is* in the count


def test_blank_code_can_match_a_unique_alias(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001"), item("ST-0009", code=None, name="6A MCB"))

    (issue,) = of_type(result, IssueType.BLANK_CODE)
    assert "alias" in issue.detail
    assert loaded(result)["ST-0009"] == 10


def test_name_differing_only_in_capitals_is_reported_but_loaded(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001"), item("ST-0009", name="mcb 6a SINGLE pole"))

    (issue,) = of_type(result, IssueType.NAME_FORMAT)
    assert "capital letters" in issue.detail
    assert "extra spaces" not in issue.detail
    assert loaded(result)["ST-0009"] == 10


def test_a_known_alias_next_to_the_code_is_accepted_quietly(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001"), item("ST-0009", name="6A MCB"))

    assert [i.issue_type for i in result.issues] == [IssueType.SKIPPED_ROW]  # just the title
    assert loaded(result)["ST-0009"] == 10


def test_row_without_code_or_name_is_rejected(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001"), item("ST-0009", code=None, name=None))

    (issue,) = of_type(result, IssueType.UNKNOWN_ITEM)
    assert issue.source_row == 4


def test_a_row_with_only_a_product_name_is_an_item_not_a_heading(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001"), [None, "MCB 6A Single Pole"])

    assert result.rows_read == 2
    assert [i.source_row for i in of_type(result, IssueType.SKIPPED_ROW)] == [1]  # just the title
    (issue,) = of_type(result, IssueType.INVALID_QTY)
    assert issue.sku == "ST-0009"


def test_grand_total_row_is_skipped(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001"), item("ST-0009"), [None, "Grand Total", None, 20])

    assert "Totals row" in of_type(result, IssueType.SKIPPED_ROW)[-1].detail
    assert result.rows_read == 2


# --- Quantity ---


@pytest.mark.parametrize(
    ("qty", "words"),
    [(None, "blank"), ("nil", "not a number"), (12.5, "not a whole number")],
)
def test_unusable_quantities_are_not_loaded(parse: Parse, qty: Any, words: str) -> None:
    result = parse(TITLE, HEADER, item("ST-0001", qty=qty), item("ST-0009"))

    (issue,) = of_type(result, IssueType.INVALID_QTY)
    assert words in issue.detail
    assert "ST-0001" not in loaded(result)


def test_quantity_text_with_a_thousands_separator(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0009", qty="1,200"), item("ST-0001"))

    assert loaded(result)["ST-0009"] == 1200
    assert of_type(result, IssueType.QTY_AS_TEXT)


def test_quantity_text_in_a_different_unit_is_not_loaded(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0009", qty="5 box"), item("ST-0001"))

    assert of_type(result, IssueType.UNIT_MISMATCH)
    assert "ST-0009" not in loaded(result)


def test_later_duplicate_with_a_bad_count_means_a_recount(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001", qty=7), item("ST-0001", qty=-1), item("ST-0009"))

    assert "ST-0001" not in loaded(result)
    (duplicate,) = of_type(result, IssueType.DUPLICATE_ROW)
    assert "recount" in duplicate.detail
    assert of_type(result, IssueType.NEGATIVE_QTY)


# --- Unit ---


def test_unit_different_from_the_master_is_not_loaded(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0009", unit="box"), item("ST-0001"))

    (issue,) = of_type(result, IssueType.UNIT_MISMATCH)
    assert "converting would be a guess" in issue.detail
    assert "ST-0009" not in loaded(result)


def test_unknown_unit_is_not_loaded(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0009", unit="dozen"), item("ST-0001"))

    assert of_type(result, IssueType.UNKNOWN_UNIT)
    assert "ST-0009" not in loaded(result)


def test_blank_unit_assumes_the_master_unit(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0009", unit=None), item("ST-0001"))

    (issue,) = of_type(result, IssueType.BLANK_UNIT)
    assert issue.severity == "warning"
    assert loaded(result)["ST-0009"] == 10


# --- Rates and supplier (compared with the master, never written back) ---


def test_rate_that_differs_from_the_master_is_reported(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001", purchase=1200), item("ST-0009"))

    (issue,) = of_type(result, IssueType.RATE_MISMATCH)
    assert "₹1200.00" in issue.detail
    assert "₹1150.00" in issue.detail
    assert loaded(result)["ST-0001"] == 10


def test_rates_written_with_rupee_signs_and_commas_match(parse: Parse) -> None:
    result = parse(
        TITLE, HEADER, item("ST-0001", purchase="₹ 1,150", sale="Rs. 1390"), item("ST-0009")
    )

    assert not of_type(result, IssueType.RATE_MISMATCH)
    assert not of_type(result, IssueType.INVALID_RATE)


def test_rate_that_is_not_a_number(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001", sale="n/a"), item("ST-0009"))

    assert of_type(result, IssueType.INVALID_RATE)


def test_both_rates_blank_is_a_single_issue(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001", purchase=None, sale=None), item("ST-0009"))

    (issue,) = of_type(result, IssueType.BLANK_RATE)
    assert "Purchase rate and sale rate" in issue.detail


def test_short_name_that_fits_two_suppliers_is_not_guessed(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0009", supplier="Volta"), item("ST-0001"))

    assert of_type(result, IssueType.UNKNOWN_SUPPLIER)
    assert loaded(result)["ST-0009"] == 10


def test_supplier_that_differs_from_the_master_is_reported(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0009", supplier="Kiran Cables Pvt Ltd"), item("ST-0001"))

    (issue,) = of_type(result, IssueType.SUPPLIER_MISMATCH)
    assert "Volta Switchgear (SUP02)" in issue.detail


# --- Remarks ---


def test_ordered_remark_with_the_words_in_another_order(parse: Parse) -> None:
    result = parse(
        TITLE, HEADER, item("ST-0001", remarks="ordered 5 coils from Kiran"), item("ST-0009")
    )

    assert result.po_notes == (
        PoNote("ST-0001", "SUP01", 5, None, "ordered 5 coils from Kiran", 3),
    )


@pytest.mark.parametrize("remark", ["PO placed yesterday", "2 box ordered from Volta Switchgear"])
def test_unclear_order_remarks_are_not_counted_as_on_order(parse: Parse, remark: str) -> None:
    result = parse(TITLE, HEADER, item("ST-0009", remarks=remark), item("ST-0001"))

    assert of_type(result, IssueType.UNCLEAR_PO_REMARK)
    assert result.po_notes == ()


def test_dates_without_a_year_across_new_year(parse: Parse) -> None:
    result = parse(
        ["Count taken 3/1"],
        HEADER,
        item("ST-0001", remarks="5 coils ordered from Kiran on 28/12"),
        item("ST-0009"),
        today=date(2027, 1, 5),
    )

    assert result.as_of == date(2027, 1, 3)
    (note,) = result.po_notes
    assert note.ordered_on == date(2026, 12, 28)


# --- Whole file ---


def test_product_missing_from_the_count_is_reported(parse: Parse) -> None:
    result = parse(TITLE, HEADER, item("ST-0001"))

    (issue,) = of_type(result, IssueType.MISSING_FROM_REGISTER)
    assert (issue.sku, issue.source_row, issue.severity) == ("ST-0009", None, "warning")


def test_other_sheets_with_content_are_reported(parse: Parse) -> None:
    result = parse(
        TITLE,
        HEADER,
        item("ST-0001"),
        item("ST-0009"),
        other_sheets={"Notes": [["recheck MCBs"]], "Empty": []},
    )

    (issue,) = of_type(result, IssueType.OTHER_SHEET)
    assert "recheck MCBs" in issue.detail
