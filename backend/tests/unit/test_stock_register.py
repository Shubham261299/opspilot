"""The real sample file: one test per problem planted in stock_register.xlsx."""

from datetime import date
from pathlib import Path

import pytest

from app.domain.catalog import Catalog
from app.intake.issues import IssueRecord, IssueType
from app.intake.stock_register import (
    PoNote,
    StockRegisterResult,
    StockRow,
    parse_stock_register,
)

UPLOAD_DAY = date(2026, 9, 29)


@pytest.fixture(scope="module")
def result(sample_data_dir: Path, catalog: Catalog) -> StockRegisterResult:
    content = (sample_data_dir / "stock_register.xlsx").read_bytes()
    return parse_stock_register(content, catalog, today=UPLOAD_DAY)


def issue_at(result: StockRegisterResult, row: int, issue_type: IssueType) -> IssueRecord:
    matches = [i for i in result.issues if i.source_row == row and i.issue_type == issue_type]
    assert len(matches) == 1, f"expected one {issue_type} issue on row {row}, got {matches}"
    return matches[0]


def stock(result: StockRegisterResult, sku: str) -> StockRow | None:
    return next((row for row in result.stock_rows if row.sku == sku), None)


def test_header_is_found_below_the_title_rows(result: StockRegisterResult) -> None:
    assert (result.sheet_name, result.header_row) == ("Stock Sep", 4)


def test_title_rows_are_skipped_and_give_the_count_date(result: StockRegisterResult) -> None:
    assert result.as_of == date(2026, 9, 24)  # from "Updated by Ravi on 24/9 evening"
    assert issue_at(result, 1, IssueType.SKIPPED_ROW).severity == "info"
    assert "24 Sep 2026" in issue_at(result, 2, IssueType.SKIPPED_ROW).detail


def test_section_heading_row_is_skipped(result: StockRegisterResult) -> None:
    issue = issue_at(result, 35, IssueType.SKIPPED_ROW)
    assert "Switches & Sockets" in issue.detail


def test_totals_footer_is_skipped(result: StockRegisterResult) -> None:
    assert "TOTAL ITEMS" in issue_at(result, 69, IssueType.SKIPPED_ROW).detail


def test_mixed_unit_spellings_are_normalised_and_listed_once(result: StockRegisterResult) -> None:
    (issue,) = [i for i in result.issues if i.issue_type == IssueType.UNITS_NORMALISED]
    assert issue.source_row is None  # about the whole file
    assert issue.raw is not None
    assert {"NOS → piece", "Coil → coil", "coils → coil", "Lgth → length", "Pkt → packet"} <= set(
        issue.raw
    )
    assert 6 in issue.raw["NOS → piece"]  # USB Charger Socket, "NOS"


def test_quantity_typed_as_text_is_read_as_a_number(result: StockRegisterResult) -> None:
    issue = issue_at(result, 41, IssueType.QTY_AS_TEXT)
    assert "395 pcs" in issue.detail
    assert stock(result, "ST-0028") == StockRow("ST-0028", 395, 41, None)


def test_negative_quantity_is_not_loaded(result: StockRegisterResult) -> None:
    issue = issue_at(result, 63, IssueType.NEGATIVE_QTY)
    assert (issue.severity, issue.sku) == ("error", "ST-0040")
    assert stock(result, "ST-0040") is None


def test_blank_rates_are_reported_and_the_rows_still_load(result: StockRegisterResult) -> None:
    sale = issue_at(result, 37, IssueType.BLANK_RATE)
    purchase = issue_at(result, 42, IssueType.BLANK_RATE)
    assert (sale.sku, purchase.sku) == ("ST-0019", "ST-0009")
    assert "Sale rate" in sale.detail
    assert "Purchase rate" in purchase.detail
    assert stock(result, "ST-0019") is not None
    assert stock(result, "ST-0009") is not None


def test_blank_item_code_is_matched_by_exact_name(result: StockRegisterResult) -> None:
    issue = issue_at(result, 5, IssueType.BLANK_CODE)
    assert issue.sku == "ST-0052"
    assert stock(result, "ST-0052") == StockRow("ST-0052", 54, 5, None)


def test_duplicate_row_keeps_the_later_count(result: StockRegisterResult) -> None:
    issue = issue_at(result, 20, IssueType.DUPLICATE_ROW)
    assert "row 7" in issue.detail
    assert "157" in issue.detail
    assert stock(result, "ST-0036") == StockRow("ST-0036", 164, 20, "recount")


def test_supplier_short_name_is_resolved(result: StockRegisterResult) -> None:
    issue = issue_at(result, 52, IssueType.SUPPLIER_SHORT_NAME)
    assert "Volta Switchgear (SUP02)" in issue.detail
    assert stock(result, "ST-0014") is not None


def test_discontinued_item_not_in_the_master_is_rejected(result: StockRegisterResult) -> None:
    issue = issue_at(result, 67, IssueType.UNKNOWN_ITEM)
    assert issue.severity == "error"
    assert issue.sku is None
    assert "discontinued" in issue.detail


def test_ordered_remark_becomes_an_open_po_note(result: StockRegisterResult) -> None:
    assert result.po_notes == (
        PoNote(
            sku="ST-0021",
            supplier_code="SUP03",
            qty=40,
            ordered_on=date(2026, 9, 22),
            note="40 pcs ordered from Brightline on 22/9",
            source_row=55,
        ),
    )
    assert issue_at(result, 55, IssueType.OPEN_PO_NOTE).severity == "info"
    stock_row = stock(result, "ST-0021")
    assert stock_row is not None
    assert stock_row.qty_on_hand == 10  # stock on hand is unchanged by the order


def test_order_urgent_is_a_request_not_a_placed_order(result: StockRegisterResult) -> None:
    assert stock(result, "ST-0047") == StockRow("ST-0047", 0, 32, "finished!! order urgent")
    assert not [i for i in result.issues if i.source_row == 32]


def test_name_with_extra_spaces_and_lowercase_loads_and_is_reported(
    result: StockRegisterResult,
) -> None:
    issue = issue_at(result, 19, IssueType.NAME_FORMAT)
    assert (issue.severity, issue.sku) == ("info", "ST-0033")
    assert "extra spaces and capital letters" in issue.detail
    assert issue.raw is not None
    assert issue.raw["Item Name"] == "  gi box 8 module  "  # kept exactly as typed
    assert stock(result, "ST-0033") == StockRow("ST-0033", 34, 19, None)


def test_the_notes_sheet_is_reported_not_imported(result: StockRegisterResult) -> None:
    (issue,) = [i for i in result.issues if i.issue_type == IssueType.OTHER_SHEET]
    assert "Godown 2 stock not counted this week" in issue.detail


def test_totals(result: StockRegisterResult) -> None:
    assert result.rows_read == 62  # item rows between the header and the footer
    assert len(result.stock_rows) == 59  # 60 products, minus ST-0040 (negative count)
    assert len({row.sku for row in result.stock_rows}) == 59
    assert not [i for i in result.issues if i.issue_type == IssueType.MISSING_FROM_REGISTER]


def test_only_rows_with_a_planted_problem_get_an_issue(result: StockRegisterResult) -> None:
    rows_with_issues = {i.source_row for i in result.issues if i.source_row is not None}
    assert rows_with_issues == {1, 2, 5, 19, 20, 35, 37, 41, 42, 52, 55, 63, 67, 69}


def test_every_row_issue_keeps_the_original_cells(result: StockRegisterResult) -> None:
    for issue in result.issues:
        assert issue.detail
        if issue.source_row is not None:
            assert issue.raw, issue
    assert issue_at(result, 63, IssueType.NEGATIVE_QTY).raw == {
        "Item Code": "ST-0040",
        "Item Name": "Bell Push Modular",
        "Unit": "piece",
        "Qty In Stock": -4,
        "Rate (Purchase)": 32,
        "MRP / Sale Rate": 52,
        "Supplier": "Modula Switches",
    }
