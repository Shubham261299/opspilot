"""The company policy PDF -> numbered rules, ready to be embedded and stored.

The policy prints its rules as numbered paragraphs under numbered headings:

    1. Stock and reordering                  <- a section heading
     1.1 Safety stock is 3 days ...          <- a rule: "section.number", then its text
     1.4 Reorder quantity = enough to ...
         rounded UP to the supplier's ...    <- a line that continues the rule above

Code splits it (no language model is involved), so a rule's number and wording are exactly what
was printed. Anything that is neither a heading, a rule nor the page title becomes an issue.
"""

import re
from dataclasses import dataclass, field

from app.intake.errors import IntakeError
from app.intake.invoice_pdf import pdf_text
from app.intake.issues import IssueRecord, IssueType

_RULE = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+(\S.*)$")  # "2.4  Put new orders ON HOLD ..."
_HEADING = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")  # "2.  Customer credit"
_VERSION = re.compile(r"^version\s+\S+", re.IGNORECASE)  # "Version 3, effective 1 April 2026. ..."


@dataclass(frozen=True)
class PolicyRuleText:
    code: str  # as printed, e.g. "2.4"
    section_no: int
    section_title: str
    text: str  # the whole rule, its wrapped lines joined with single spaces
    source_row: int  # line of the PDF text where the rule starts


@dataclass
class PolicyReading:
    title: str | None = None
    version: str | None = None  # e.g. "Version 3, effective 1 April 2026. Owner: Vinod Sharma."
    rules: list[PolicyRuleText] = field(default_factory=list)
    issues: list[IssueRecord] = field(default_factory=list)


def embedding_text(rule: PolicyRuleText) -> str:
    """What is embedded for a rule: its section title and its wording. The title gives context
    a short rule lacks ("Reminders must be polite..." is about *customer credit*)."""
    return f"{rule.section_title}: {rule.text}" if rule.section_title else rule.text


def read_policy_pdf(content: bytes) -> PolicyReading:
    """Raises IntakeError for a file that isn't a readable PDF with text, or has no rules."""
    text = pdf_text(content, scanned_hint="A scanned policy can't be read yet.")
    return parse_policy_text(text)


def parse_policy_text(text: str) -> PolicyReading:
    reading = PolicyReading()
    headings: dict[int, str] = {}
    current: _Open | None = None
    seen: set[str] = set()

    def close() -> None:
        nonlocal current
        if current is not None:
            reading.rules.append(current.finish(headings))
            current = None

    for row, line in enumerate((raw.strip() for raw in text.splitlines()), start=1):
        if not line:
            continue
        rule, heading = _RULE.match(line), _HEADING.match(line)
        if rule:
            close()
            code = f"{int(rule[1])}.{int(rule[2])}"
            if code in seen:
                reading.issues.append(
                    IssueRecord(
                        IssueType.DUPLICATE_ROW,
                        f"Rule {code} appears more than once; the first one was kept and this "
                        "one was skipped. Check the policy file.",
                        source_row=row,
                        raw={"line": line},
                    )
                )
                current = None  # its continuation lines are skipped too, below
                continue
            seen.add(code)
            current = _Open(code, int(rule[1]), row, [rule[3]])
        elif heading:
            close()
            headings[int(heading[1])] = heading[2].strip()
        elif current is not None:
            current.lines.append(line)  # a wrapped line of the rule above
        elif reading.title is None and not reading.rules:
            reading.title = line  # the first line before any heading: the document's title
        elif reading.version is None and _VERSION.match(line):
            reading.version = line
        else:
            reading.issues.append(
                IssueRecord(
                    IssueType.SKIPPED_ROW,
                    "This line is not a section heading or a numbered rule, so it was not "
                    "stored as policy.",
                    source_row=row,
                    raw={"line": line},
                )
            )
    close()
    if not reading.rules:
        raise IntakeError(
            "no_rules",
            "No numbered rules (like '2.4 Put new orders on hold ...') were found in the PDF.",
        )
    return reading


@dataclass
class _Open:
    """A rule being collected: its first line, then the lines that continue it."""

    code: str
    section_no: int
    row: int
    lines: list[str]

    def finish(self, headings: dict[int, str]) -> PolicyRuleText:
        return PolicyRuleText(
            code=self.code,
            section_no=self.section_no,
            section_title=headings.get(self.section_no, ""),
            text=" ".join(self.lines),
            source_row=self.row,
        )
