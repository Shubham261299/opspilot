"""Reading the company policy PDF into numbered rules."""

from pathlib import Path

import pytest

from app.intake.errors import IntakeError
from app.intake.issues import IssueType
from app.intake.policy import embedding_text, parse_policy_text, read_policy_pdf

ALL_CODES = [
    "1.1", "1.2", "1.3", "1.4", "1.5",
    "2.1", "2.2", "2.3", "2.4", "2.5",
    "3.1", "3.2", "3.3",
    "4.1", "4.2",
]  # fmt: skip


def test_the_sample_policy_gives_all_fifteen_rules_with_no_issues(sample_data_dir: Path) -> None:
    reading = read_policy_pdf((sample_data_dir / "company_policy.pdf").read_bytes())
    assert [rule.code for rule in reading.rules] == ALL_CODES
    assert reading.issues == []
    assert reading.title == "Sharma Traders - Operating Policy"
    assert reading.version is not None and reading.version.startswith("Version 3")


def test_sections_and_wrapped_lines_are_read_as_printed(sample_data_dir: Path) -> None:
    reading = read_policy_pdf((sample_data_dir / "company_policy.pdf").read_bytes())
    rules = {rule.code: rule for rule in reading.rules}
    assert (rules["2.4"].section_no, rules["2.4"].section_title) == (2, "Customer credit")
    assert rules["4.2"].section_title == "Supplier invoices"
    # 1.4 and 1.5 wrap onto a second printed line; the rule is one text.
    assert rules["1.4"].text.endswith("rounded UP to the supplier's pack size.")
    assert "Below that, the store manager may approve." in rules["1.5"].text
    assert "\n" not in rules["1.5"].text


def test_the_embedded_text_starts_with_the_section_title() -> None:
    reading = parse_policy_text("Title\n2. Customer credit\n2.2 A bill is overdue when unpaid.")
    assert embedding_text(reading.rules[0]) == "Customer credit: A bill is overdue when unpaid."


def test_a_rule_without_a_heading_is_still_kept() -> None:
    [rule] = parse_policy_text("Title\n7.1 Lock the godown at night.").rules
    assert (rule.code, rule.section_title) == ("7.1", "")
    assert embedding_text(rule) == "Lock the godown at night."


def test_a_repeated_rule_number_keeps_the_first_and_reports_the_rest() -> None:
    text = "Title\n1. Stock\n1.1 First wording.\n1.1 Second wording.\n  carried on here\n1.2 Next."
    reading = parse_policy_text(text)
    assert [(rule.code, rule.text) for rule in reading.rules] == [
        ("1.1", "First wording."),
        ("1.2", "Next."),
    ]
    types = [issue.issue_type for issue in reading.issues]
    assert types == [IssueType.DUPLICATE_ROW, IssueType.SKIPPED_ROW]  # the repeat, its 2nd line


def test_a_stray_line_before_any_rule_is_reported_not_dropped() -> None:
    text = (
        "Title\nVersion 2, effective 1 May 2026.\nSee also the staff handbook\n1. Stock\n1.1 Rule."
    )
    reading = parse_policy_text(text)
    assert [rule.code for rule in reading.rules] == ["1.1"]
    assert reading.version == "Version 2, effective 1 May 2026."
    [issue] = reading.issues
    assert issue.issue_type is IssueType.SKIPPED_ROW
    assert issue.raw == {"line": "See also the staff handbook"}
    assert issue.source_row == 3


def test_text_without_any_numbered_rule_is_refused() -> None:
    with pytest.raises(IntakeError) as error:
        parse_policy_text("Title\nJust a paragraph about nothing in particular.")
    assert error.value.code == "no_rules"


def test_a_file_that_is_not_a_pdf_is_refused() -> None:
    with pytest.raises(IntakeError) as error:
        read_policy_pdf(b"not a pdf")
    assert error.value.code == "unreadable_file"
