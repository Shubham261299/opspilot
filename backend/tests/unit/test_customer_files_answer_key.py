"""Score the customers and dues cleaners against sample_data/answer_key.json.

The answer key is used ONLY in tests, never by the app. This file reads just its
`data_issues` entries for customers.xlsx and outstanding_dues.xlsx.
"""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.intake.customers import parse_customers
from app.intake.issues import IssueRecord, IssueType
from app.intake.outstanding_dues import parse_outstanding_dues

FILES = ("customers.xlsx", "outstanding_dues.xlsx")
ANSWER_KEY = Path(__file__).resolve().parents[3] / "sample_data" / "answer_key.json"

EXPECTED: list[dict[str, Any]] = [
    issue
    for issue in json.loads(ANSWER_KEY.read_text(encoding="utf-8"))["data_issues"]
    if issue["file"] in FILES
]

# How each kind of problem named in the answer key shows up in our issues.
SHOWS_UP_AS: dict[str, Callable[[IssueRecord], bool]] = {
    "duplicate_customer": lambda i: i.issue_type == IssueType.DUPLICATE_CUSTOMER,
    "phone_formats": lambda i: i.issue_type == IssueType.PHONES_NORMALISED,
    "mixed_date_types": lambda i: i.issue_type == IssueType.DATES_AS_TEXT,
    "party_by_name": lambda i: i.issue_type == IssueType.PARTY_BY_NAME,
}


@pytest.fixture(scope="module")
def issues_by_file(sample_data_dir: Path) -> dict[str, tuple[IssueRecord, ...]]:
    customers = parse_customers((sample_data_dir / "customers.xlsx").read_bytes())
    dues = parse_outstanding_dues(
        (sample_data_dir / "outstanding_dues.xlsx").read_bytes(),
        {c.code: c.shop_name for c in customers.customers},
        today=date(2026, 9, 24),
    )
    return {"customers.xlsx": customers.issues, "outstanding_dues.xlsx": dues.issues}


def _matches(expected: dict[str, Any], issue: IssueRecord) -> bool:
    shows_up_as = SHOWS_UP_AS.get(expected["issue"])
    return shows_up_as is not None and shows_up_as(issue)


def test_the_answer_key_lists_problems_for_these_files() -> None:
    assert {issue["file"] for issue in EXPECTED} == set(FILES)


@pytest.mark.parametrize("expected", EXPECTED, ids=lambda e: f"{e['file']}-{e['issue']}")
def test_every_planted_problem_is_reported(
    issues_by_file: dict[str, tuple[IssueRecord, ...]], expected: dict[str, Any]
) -> None:
    assert expected["issue"] in SHOWS_UP_AS, f"new kind of issue in the answer key: {expected}"
    assert any(_matches(expected, i) for i in issues_by_file[expected["file"]]), (
        f"not reported: {expected['detail']}"
    )


@pytest.mark.parametrize("file", FILES)
def test_every_error_or_warning_is_a_planted_problem(
    issues_by_file: dict[str, tuple[IssueRecord, ...]], file: str
) -> None:
    planted = [e for e in EXPECTED if e["file"] == file]
    serious = [i for i in issues_by_file[file] if i.severity in ("error", "warning")]
    assert not [i for i in serious if not any(_matches(e, i) for e in planted)]
