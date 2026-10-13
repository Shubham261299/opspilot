"""The evals as tests, played back from the recorded tapes (no model, same result every time).

What this proves: the reading code, the checks and the scoring still turn the *recorded* model
answers into the *recorded* score. If someone breaks the parser, the matching or the scorer,
the score changes and these fail. What it does not prove is that the model is good: that comes
from a real run (`python evals/run.py all`), whose numbers go in the README.

If a test says the tape is out of date, a prompt or an output schema changed since recording:
run `python evals/run.py all --record` with the real model and commit the new tapes.
"""

import pytest

from evals import invoices, whatsapp
from evals.common import RECORDINGS, CountingAsk
from evals.tape import ReplayCompletion, Tape

SUITES = {whatsapp.SUITE: whatsapp, invoices.SUITE: invoices}


@pytest.mark.parametrize("name", SUITES)
async def test_the_replayed_score_matches_the_recorded_one(name: str) -> None:
    tape = Tape.load(RECORDINGS / f"{name}.json")
    replay = ReplayCompletion(tape)
    report = await SUITES[name].run(CountingAsk(replay))
    assert replay.misses == [], "the tape is out of date: record it again with the real model"
    assert report.summary == tape.expected_summary
