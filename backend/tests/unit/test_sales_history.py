from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.intake.errors import IntakeError
from app.intake.issues import IssueType
from app.intake.sales_history import SalesResult, parse_sales_history

CUSTOMERS = {"CUS001", "CUS002"}
SKUS = {"ST-0001", "ST-0002"}
HEADER = "date,customer_id,sku,qty,unit_price,amount\n"


def parse(*lines: str) -> SalesResult:
    return parse_sales_history((HEADER + "\n".join(lines)).encode(), CUSTOMERS, SKUS)


def test_the_real_export_loads_completely(sample_data_dir: Path) -> None:
    customers = {f"CUS{n:03}" for n in range(1, 26)}
    skus = {f"ST-{n:04}" for n in range(1, 61)}
    content = (sample_data_dir / "sales_history_90d.csv").read_bytes()
    result = parse_sales_history(content, customers, skus)
    assert (result.rows_read, len(result.sales), result.issues) == (8331, 8331, ())
    assert result.last_sale == date(2026, 9, 24)


def test_a_clean_line() -> None:
    result = parse_sales_history(
        (HEADER + "2026-09-01,cus001,st-0001,2,1390,2780\n").encode("utf-8-sig"), CUSTOMERS, SKUS
    )
    [sale] = result.sales
    assert (sale.customer_code, sale.sku, sale.qty, sale.amount, sale.source_row) == (
        "CUS001",
        "ST-0001",
        2,
        Decimal(2780),
        2,
    )


@pytest.mark.parametrize(
    ("line", "issue_type"),
    [
        ("2026-09-01,CUS999,ST-0001,2,1390,2780", IssueType.UNKNOWN_CUSTOMER),
        ("2026-09-01,CUS001,ST-9999,2,1390,2780", IssueType.UNKNOWN_ITEM),
        ("2026-09-01,CUS001,ST-0001,0,1390,0", IssueType.INVALID_SALE),
        ("2026-09-01,CUS001,ST-0001,two,1390,2780", IssueType.INVALID_SALE),
        ("01/09/2026,CUS001,ST-0001,2,1390,2780", IssueType.INVALID_SALE),
    ],
)
def test_a_line_that_cant_be_trusted_is_not_loaded(line: str, issue_type: IssueType) -> None:
    result = parse(line)
    assert result.sales == ()
    assert [i.issue_type for i in result.issues] == [issue_type]


def test_a_wrong_amount_is_recalculated_with_a_warning() -> None:
    result = parse_sales_history(
        (HEADER + "2026-09-01,CUS001,ST-0001,2,1390,2000").encode(), CUSTOMERS, SKUS
    )
    assert result.sales[0].amount == Decimal(2780)
    assert result.issues[0].issue_type == IssueType.AMOUNT_MISMATCH


def test_a_file_without_the_needed_columns_is_refused() -> None:
    with pytest.raises(IntakeError) as error:
        parse_sales_history(b"when,who\n2026-09-01,CUS001\n", CUSTOMERS, SKUS)
    assert error.value.code == "header_not_found"


def test_sales_need_customers_first() -> None:
    with pytest.raises(IntakeError) as error:
        parse_sales_history(HEADER.encode(), set(), SKUS)
    assert error.value.code == "no_customers"
