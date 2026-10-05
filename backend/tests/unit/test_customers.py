from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from app.intake.customers import CustomersResult, parse_customers
from app.intake.errors import IntakeError
from app.intake.issues import IssueType

HEADER = ["Party Code", "Shop Name", "Contact Person", "Mobile", "Area", "Credit Limit", "Days"]
RAMESH = ["CUS001", "Ramesh Electricals", "Ramesh Patil", "98958-22412", "Hadapsar", 50000, 15]


@pytest.fixture(scope="module")
def result(sample_data_dir: Path) -> CustomersResult:
    return parse_customers((sample_data_dir / "customers.xlsx").read_bytes())


def of_type(result: CustomersResult, issue_type: IssueType) -> list:
    return [issue for issue in result.issues if issue.issue_type == issue_type]


# The real file ---------------------------------------------------------------------


def test_the_25_coded_customers_load(result: CustomersResult) -> None:
    assert (result.header_row, result.rows_read, len(result.customers)) == (1, 26, 25)
    assert [c.code for c in result.customers] == [f"CUS{n:03}" for n in range(1, 26)]
    first = result.customers[0]
    assert (first.shop_name, first.credit_limit, first.credit_days) == (
        "Ramesh Electricals",
        Decimal(50000),
        15,
    )


def test_every_phone_is_saved_the_same_way(result: CustomersResult) -> None:
    assert all(c.phone and len(c.phone) == 13 and c.phone[:3] == "+91" for c in result.customers)
    by_code = {c.code: c.phone for c in result.customers}
    assert by_code["CUS004"] == "+919889254563"  # written "+91 98892 54563"
    assert by_code["CUS009"] == "+919810872248"  # written "09810872248"


def test_the_four_phone_formats_are_reported_once(result: CustomersResult) -> None:
    [issue] = of_type(result, IssueType.PHONES_NORMALISED)
    assert issue.severity == "info"
    assert set(issue.raw or {}) == {"plain", "dashes", "country code", "leading zero"}


def test_the_shop_without_a_code_is_a_duplicate_of_cus001(result: CustomersResult) -> None:
    [issue] = of_type(result, IssueType.DUPLICATE_CUSTOMER)
    assert (issue.source_row, issue.customer_code, issue.severity) == (27, "CUS001", "error")
    assert "same mobile number" in issue.detail


def test_nothing_else_is_reported(result: CustomersResult) -> None:
    assert {issue.issue_type for issue in result.issues} == {
        IssueType.PHONES_NORMALISED,
        IssueType.DUPLICATE_CUSTOMER,
    }


# Rules, on small made-up sheets ------------------------------------------------------


def test_a_repeated_code_keeps_the_later_row(make_xlsx: Callable[..., bytes]) -> None:
    later = ["CUS001", "Ramesh Electricals", "Ramesh Patil", "9895822412", "Hadapsar", 80000, 30]
    result = parse_customers(make_xlsx([HEADER, RAMESH, later]))
    [customer] = result.customers
    assert (customer.credit_limit, customer.source_row) == (Decimal(80000), 3)
    [issue] = of_type(result, IssueType.DUPLICATE_ROW)
    assert issue.source_row == 3


@pytest.mark.parametrize(
    ("limit", "days"), [("", 15), ("lots", 15), (50000, ""), (-1, 15), (50000, 1.5)]
)
def test_missing_or_invalid_credit_terms_are_not_loaded(
    make_xlsx: Callable[..., bytes], limit: object, days: object
) -> None:
    row = [*RAMESH[:5], limit, days]
    result = parse_customers(make_xlsx([HEADER, row]))
    assert result.customers == ()
    assert [i.issue_type for i in result.issues] == [IssueType.INVALID_CREDIT_TERMS]


def test_a_new_shop_without_a_code_is_not_given_one(make_xlsx: Callable[..., bytes]) -> None:
    new_shop = ["", "Sunrise Electricals", "Asha", "9822012345", "Baner", 50000, 15]
    result = parse_customers(make_xlsx([HEADER, RAMESH, new_shop]))
    assert [c.code for c in result.customers] == ["CUS001"]
    [issue] = of_type(result, IssueType.MISSING_CUSTOMER_CODE)
    assert issue.source_row == 3


def test_a_codeless_row_with_almost_the_same_name_is_a_likely_duplicate(
    make_xlsx: Callable[..., bytes],
) -> None:
    twin = ["", "RAMESH  ELECTRICAL", "", "", "Hadapsar", "", ""]
    result = parse_customers(make_xlsx([HEADER, RAMESH, twin]))
    [issue] = of_type(result, IssueType.DUPLICATE_CUSTOMER)
    assert "almost the same shop name" in issue.detail


def test_an_invalid_phone_is_reported_and_the_customer_still_loads(
    make_xlsx: Callable[..., bytes],
) -> None:
    row = [*RAMESH[:3], "12345", *RAMESH[4:]]
    result = parse_customers(make_xlsx([HEADER, row]))
    assert result.customers[0].phone is None
    assert [i.issue_type for i in result.issues] == [IssueType.INVALID_PHONE]


def test_a_code_without_a_shop_name_is_not_loaded(make_xlsx: Callable[..., bytes]) -> None:
    row = ["CUS001", "", *RAMESH[2:]]
    result = parse_customers(make_xlsx([HEADER, row]))
    assert result.customers == ()
    assert [i.issue_type for i in result.issues] == [IssueType.MISSING_SHOP_NAME]


def test_a_sheet_without_the_needed_columns_is_refused(make_xlsx: Callable[..., bytes]) -> None:
    with pytest.raises(IntakeError) as error:
        parse_customers(make_xlsx([["Name", "Phone"], ["Ramesh", "9895822412"]]))
    assert error.value.code == "header_not_found"
