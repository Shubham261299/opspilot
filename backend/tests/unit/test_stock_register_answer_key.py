"""Score the stock register cleaner against sample_data/answer_key.json.

The answer key is used ONLY in tests, never by the app. This file reads just its
`data_issues` entries for stock_register.xlsx.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.domain.catalog import Catalog
from app.intake.issues import IssueRecord, IssueType
from app.intake.stock_register import StockRegisterResult, parse_stock_register

FILE = "stock_register.xlsx"
ANSWER_KEY = Path(__file__).resolve().parents[3] / "sample_data" / "answer_key.json"

EXPECTED: list[dict[str, Any]] = [
    issue
    for issue in json.loads(ANSWER_KEY.read_text(encoding="utf-8"))["data_issues"]
    if issue["file"] == FILE
]

# How each kind of problem named in the answer key shows up in our issues.
SHOWS_UP_AS: dict[str, Callable[[IssueRecord], bool]] = {
    "missing_value": lambda i: (
        i.issue_type in {IssueType.BLANK_RATE, IssueType.BLANK_UNIT, IssueType.INVALID_QTY}
    ),
    "qty_as_text": lambda i: i.issue_type == IssueType.QTY_AS_TEXT,
    "negative_qty": lambda i: i.issue_type == IssueType.NEGATIVE_QTY,
    "name_format": lambda i: i.issue_type == IssueType.NAME_FORMAT,
    "missing_code": lambda i: i.issue_type == IssueType.BLANK_CODE,
    "duplicate_row": lambda i: i.issue_type == IssueType.DUPLICATE_ROW,
    "supplier_alias": lambda i: i.issue_type == IssueType.SUPPLIER_SHORT_NAME,
    "section_header_row": lambda i: (
        i.issue_type == IssueType.SKIPPED_ROW and i.detail.startswith("Section heading")
    ),
    "footer_row": lambda i: (
        i.issue_type == IssueType.SKIPPED_ROW and i.detail.startswith("Totals row")
    ),
    "unknown_item": lambda i: i.issue_type == IssueType.UNKNOWN_ITEM,
}


@pytest.fixture(scope="module")
def result(sample_data_dir: Path, catalog: Catalog) -> StockRegisterResult:
    content = (sample_data_dir / FILE).read_bytes()
    return parse_stock_register(content, catalog, today=date(2026, 9, 29))


def _matches(expected: dict[str, Any], issue: IssueRecord) -> bool:
    shows_up_as = SHOWS_UP_AS.get(expected["issue"])
    return shows_up_as is not None and shows_up_as(issue) and expected["sku"] in (None, issue.sku)


def test_the_answer_key_lists_problems_for_this_file() -> None:
    assert EXPECTED  # guards against an empty list making the tests below pass vacuously


@pytest.mark.parametrize("expected", EXPECTED, ids=lambda e: f"{e['issue']}-{e['sku'] or 'no_sku'}")
def test_every_planted_problem_is_reported(
    result: StockRegisterResult, expected: dict[str, Any]
) -> None:
    assert expected["issue"] in SHOWS_UP_AS, f"new kind of issue in the answer key: {expected}"
    assert any(_matches(expected, issue) for issue in result.issues), (
        f"not reported: {expected['detail']}"
    )


def test_every_error_or_warning_is_a_planted_problem(result: StockRegisterResult) -> None:
    serious = [i for i in result.issues if i.severity in ("error", "warning")]
    unexplained = [i for i in serious if not any(_matches(e, i) for e in EXPECTED)]
    assert not unexplained
