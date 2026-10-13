"""Which policy rules a proposal cites: a fixed mapping from what the proposal carries."""

from pathlib import Path

from app.domain.policy_rules import citations_for
from app.intake.policy import read_policy_pdf


def codes(kind: str, **numbers: object) -> list[str]:
    return [c.code for c in citations_for(kind, numbers)]


def test_a_reorder_follows_the_reorder_rules_and_the_owner_limit_when_it_applies() -> None:
    assert codes("reorder", needs_owner=False) == ["1.2", "1.3", "1.4"]
    assert codes("reorder", needs_owner=True) == ["1.2", "1.3", "1.4", "1.5"]


def test_a_reminder_follows_the_reminder_and_tone_rules_and_says_how_overdue() -> None:
    [overdue, tone] = citations_for("payment_reminder", {"max_days_overdue": 11})
    assert (overdue.code, tone.code) == ("2.3", "2.5")
    assert "11 days overdue" in overdue.why


def test_a_hold_says_which_condition_put_the_customer_on_hold() -> None:
    [late] = citations_for("hold_orders", {"max_days_overdue": 33, "over_limit": False})
    assert late.code == "2.4" and "33 days overdue" in late.why and "credit limit" not in late.why
    [both] = citations_for("hold_orders", {"max_days_overdue": 40, "over_limit": True})
    assert "40 days overdue" in both.why and "above the credit limit" in both.why
    [limit_only] = citations_for("hold_orders", {"max_days_overdue": 12, "over_limit": True})
    assert "days overdue" not in limit_only.why and "above the credit limit" in limit_only.why


def test_an_order_cites_only_the_rules_its_flags_raise() -> None:
    assert codes("confirm_order", customer_on_hold=False, unusually_large=0, unclear=[]) == []
    assert codes("confirm_order", customer_on_hold=True, unusually_large=2, unclear=["photo"]) == [
        "2.4",
        "3.1",
        "3.2",
    ]
    assert codes("confirm_order", unusually_large=1) == ["3.1"]


def test_an_invoice_cites_the_price_check_and_the_duplicate_check() -> None:
    clean = citations_for("approve_invoice", {"price_jumps": 0})
    assert [c.code for c in clean] == ["4.1", "4.2"]
    assert clean[0].why == "Every rate is within 10% of the last purchase rate"
    one = citations_for("approve_invoice", {"price_jumps": 1})[0]
    assert one.why == "1 rate is more than 10% above the last purchase rate"
    two = citations_for("approve_invoice", {"price_jumps": 2})[0]
    assert two.why.startswith("2 rates are more than 10% above")


def test_an_unknown_kind_follows_no_rule() -> None:
    assert citations_for("something_else", {}) == []


def test_every_cited_rule_exists_in_the_sample_policy(sample_data_dir: Path) -> None:
    """If the policy is renumbered, this fails instead of citations quietly pointing elsewhere."""
    stored = {
        r.code for r in read_policy_pdf((sample_data_dir / "company_policy.pdf").read_bytes()).rules
    }
    everything = {
        "reorder": {"needs_owner": True},
        "payment_reminder": {"max_days_overdue": 9},
        "hold_orders": {"max_days_overdue": 40, "over_limit": True},
        "confirm_order": {"customer_on_hold": True, "unusually_large": 1, "unclear": ["x"]},
        "approve_invoice": {"price_jumps": 1},
    }
    cited = {c.code for kind, numbers in everything.items() for c in citations_for(kind, numbers)}
    assert cited <= stored
    assert cited == {"1.2", "1.3", "1.4", "1.5", "2.3", "2.5", "2.4", "3.1", "3.2", "4.1", "4.2"}
