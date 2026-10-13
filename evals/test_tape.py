"""The tape and the scorers, tested without any model or recording."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.intake.invoices import InvoiceLine, InvoiceReading
from evals.common import CountingAsk, load_answer_key
from evals.invoices import score_invoice
from evals.tape import RecordingCompletion, ReplayCompletion, ReplayMiss, Tape, request_key


class Answer(BaseModel):
    ok: bool


class OtherAnswer(BaseModel):
    ok: bool
    why: str = ""


ASK = [{"role": "user", "content": "hello"}]


def test_a_request_key_depends_on_the_messages_and_the_schema() -> None:
    assert request_key(ASK, Answer) == request_key(list(ASK), Answer)
    assert request_key(ASK, Answer) != request_key([{"role": "user", "content": "hi"}], Answer)
    assert request_key(ASK, Answer) != request_key(ASK, OtherAnswer)


async def test_what_is_recorded_is_played_back(tmp_path: Path) -> None:
    async def real_model(**kwargs: Any) -> Any:
        message = SimpleNamespace(content='{"ok": true}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    tape = Tape(path=tmp_path / "t.json", model="fake", recorded_at="now")
    ask = CountingAsk(RecordingCompletion(real_model, tape))
    assert await ask(ASK, Answer, "demo") == Answer(ok=True)
    tape.expected_summary = {"x": 1}
    tape.save()

    replay = ReplayCompletion(Tape.load(tmp_path / "t.json"))
    assert await CountingAsk(replay)(ASK, Answer, "demo") == Answer(ok=True)
    assert replay.misses == []


async def test_a_request_not_on_the_tape_is_listed_as_a_miss(tmp_path: Path) -> None:
    replay = ReplayCompletion(Tape(path=tmp_path / "t.json"))
    with pytest.raises(ReplayMiss):
        await replay(messages=ASK, response_format=Answer, metadata={"generation_name": "demo"})
    assert len(replay.misses) == 1
    assert replay.misses[0].startswith("demo (")


def _correct_reading(expected: dict[str, Any]) -> InvoiceReading:
    """An invoice read perfectly, built from the answer key."""
    return InvoiceReading(
        supplier_code=expected["supplier_code"],
        supplier_name="",
        supplier_gstin=None,
        invoice_no=expected["invoice_no"],
        invoice_date=date.fromisoformat(expected["invoice_date"]),
        lines=[
            InvoiceLine(
                number=n,
                description="",
                qty=Decimal(str(ln["qty"])),
                rate=Decimal(str(ln["rate"])),
                amount=Decimal(0),
                sku=ln["sku"],
                matched_on="name",
            )
            for n, ln in enumerate(expected["lines"], start=1)
        ],
        subtotal=Decimal(str(expected["subtotal"])),
        gst_rate_percent=Decimal(18),
        gst_amount=Decimal(str(expected["gst_amount"])),
        grand_total=Decimal(str(expected["grand_total"])),
        marked_duplicate=expected["marked_duplicate"],
        notes=[],
    )


def test_the_invoice_scorer_accepts_a_perfect_reading_and_catches_mistakes() -> None:
    expected = load_answer_key()["expected_invoices"][1]
    reading = _correct_reading(expected)
    assert score_invoice(expected, reading)["all_right"] is True

    reading.grand_total += Decimal("0.01")  # one paisa out
    reading.lines[0] = InvoiceLine(**{**vars(reading.lines[0]), "qty": Decimal(999)})
    scored = score_invoice(expected, reading)
    assert scored["all_right"] is False
    assert scored["lines_exact"] == scored["lines_expected"] - 1
    assert any(p.startswith("grand_total") for p in scored["problems"])
