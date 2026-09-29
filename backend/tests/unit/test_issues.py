from app.intake.issues import SEVERITY, IssueRecord, IssueType


def test_every_issue_type_has_exactly_one_severity() -> None:
    assert set(SEVERITY) == set(IssueType)


def test_issue_severity_comes_from_its_type() -> None:
    assert IssueRecord(IssueType.NEGATIVE_QTY, "qty -4").severity == "error"
    assert IssueRecord(IssueType.DUPLICATE_ROW, "twice").severity == "warning"
    assert IssueRecord(IssueType.SKIPPED_ROW, "title").severity == "info"
