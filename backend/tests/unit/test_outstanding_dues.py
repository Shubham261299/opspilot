from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.intake.customers import parse_customers
from app.intake.errors import IntakeError
from app.intake.issues import IssueType
from app.intake.outstanding_dues import DuesResult, parse_outstanding_dues

TODAY = date(2026, 9, 24)
HEADER = ["Party", "Bill No", "Bill Date", "Bill Amt", "Received", "Balance"]
CUSTOMERS = {"CUS001": "Ramesh Electricals", "CUS003": "Om Sai Hardware"}


@pytest.fixture(scope="module")
def result(sample_data_dir: Path) -> DuesResult:
    customers = parse_customers((sample_data_dir / "customers.xlsx").read_bytes()).customers
    content = (sample_data_dir / "outstanding_dues.xlsx").read_bytes()
    return parse_outstanding_dues(content, {c.code: c.shop_name for c in customers}, TODAY)


def of_type(result: DuesResult, issue_type: IssueType) -> list:
    return [issue for issue in result.issues if issue.issue_type == issue_type]


def parse(make_xlsx: Callable[..., bytes], *rows: list) -> DuesResult:
    return parse_outstanding_dues(make_xlsx([HEADER, *rows]), CUSTOMERS, TODAY)


# The real file ---------------------------------------------------------------------


def test_all_55_bills_load(result: DuesResult) -> None:
    assert (result.rows_read, len(result.bills)) == (55, 55)
    assert sum(bill.balance for bill in result.bills) == Decimal(1134000)


def test_parties_written_by_shop_name_are_matched_to_codes(result: DuesResult) -> None:
    first = result.bills[0]
    assert (first.customer_code, first.bill_no, first.balance) == (
        "CUS003",
        "ST/5402",
        Decimal(38500),
    )
    [issue] = of_type(result, IssueType.PARTY_BY_NAME)
    assert issue.raw is not None and len(issue.raw["rows"]) == 55


def test_dates_typed_as_text_are_read_day_first(result: DuesResult) -> None:
    bill = next(b for b in result.bills if b.bill_no == "ST/5128")
    assert bill.bill_date == date(2026, 8, 15)  # written "15-08-2026"
    [issue] = of_type(result, IssueType.DATES_AS_TEXT)
    assert issue.raw == {"rows": [5, 12, 19, 26, 33, 40, 47, 54]}


def test_a_blank_received_means_nothing_received(result: DuesResult) -> None:
    bill = next(b for b in result.bills if b.bill_no == "ST/5410")
    assert (bill.received, bill.balance) == (Decimal(0), Decimal(86000))
    [issue] = of_type(result, IssueType.BLANK_RECEIVED)
    assert issue.raw is not None and len(issue.raw["rows"]) == 53


def test_only_information_issues_in_the_real_file(result: DuesResult) -> None:
    assert {issue.severity for issue in result.issues} == {"info"}


# Rules, on small made-up sheets ------------------------------------------------------


def test_a_party_code_works_as_well_as_a_name(make_xlsx: Callable[..., bytes]) -> None:
    result = parse(make_xlsx, ["cus001", "ST/1", datetime(2026, 9, 1), 1000, 0, 1000])
    assert result.bills[0].customer_code == "CUS001"
    assert of_type(result, IssueType.PARTY_BY_NAME) == []


def test_an_almost_matching_name_is_not_guessed(make_xlsx: Callable[..., bytes]) -> None:
    result = parse(make_xlsx, ["Ramesh Electrical", "ST/1", datetime(2026, 9, 1), 1000, "", 1000])
    assert result.bills == ()
    [issue] = of_type(result, IssueType.UNKNOWN_CUSTOMER)
    assert (issue.severity, issue.customer_code) == ("error", "CUS001")
    assert "close to CUS001" in issue.detail


def test_a_wrong_balance_is_reported_and_recalculated(make_xlsx: Callable[..., bytes]) -> None:
    result = parse(make_xlsx, ["Om Sai Hardware", "ST/1", datetime(2026, 9, 1), 1000, 200, 900])
    assert result.bills[0].balance == Decimal(800)
    assert [i.issue_type for i in result.issues] == [
        IssueType.BALANCE_MISMATCH,
        IssueType.PARTY_BY_NAME,
    ]


def test_a_fully_paid_bill_is_not_outstanding(make_xlsx: Callable[..., bytes]) -> None:
    result = parse(make_xlsx, ["CUS003", "ST/1", datetime(2026, 9, 1), 1000, 1000, 0])
    assert result.bills == ()
    assert [i.issue_type for i in result.issues] == [IssueType.PAID_BILL]


def test_a_repeated_bill_number_keeps_the_later_row(make_xlsx: Callable[..., bytes]) -> None:
    result = parse(
        make_xlsx,
        ["CUS003", "ST/1", datetime(2026, 9, 1), 1000, "", 1000],
        ["CUS003", "ST/1", datetime(2026, 9, 1), 1200, "", 1200],
    )
    [bill] = result.bills
    assert bill.amount == Decimal(1200)
    assert of_type(result, IssueType.DUPLICATE_ROW)[0].source_row == 3


@pytest.mark.parametrize(
    "row",
    [
        ["CUS003", "", datetime(2026, 9, 1), 1000, "", 1000],
        ["CUS003", "ST/1", "sometime", 1000, "", 1000],
        ["CUS003", "ST/1", datetime(2026, 9, 1), "", "", 1000],
        ["CUS003", "ST/1", datetime(2026, 9, 1), 1000, "some", 1000],
    ],
    ids=["no bill no", "bad date", "no amount", "bad received"],
)
def test_an_unreadable_bill_is_not_loaded(make_xlsx: Callable[..., bytes], row: list) -> None:
    result = parse(make_xlsx, row)
    assert result.bills == ()
    assert [i.issue_type for i in result.issues] == [IssueType.INVALID_BILL]


def test_a_bill_dated_after_today_loads_with_a_warning(make_xlsx: Callable[..., bytes]) -> None:
    result = parse(make_xlsx, ["CUS003", "ST/1", datetime(2026, 10, 2), 1000, "", 1000])
    assert len(result.bills) == 1
    assert of_type(result, IssueType.FUTURE_BILL_DATE)[0].severity == "warning"


def test_dues_need_customers_first(make_xlsx: Callable[..., bytes]) -> None:
    with pytest.raises(IntakeError) as error:
        parse_outstanding_dues(make_xlsx([HEADER]), {}, TODAY)
    assert error.value.code == "no_customers"
