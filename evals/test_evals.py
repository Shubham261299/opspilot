"""The evals as tests, played back from the recorded tapes (no model, same result every time).

What this proves: the reading code, the checks and the scoring still turn the *recorded* model
answers into the *recorded* score. If someone breaks the parser, the matching or the scorer,
the score changes and these fail. What it does not prove is that the model is good: that comes
from a real run (`python evals/run.py all`), whose numbers go in the README.

If a test says the tape is out of date, a prompt or an output schema changed since recording:
run `python evals/run.py all --record` with the real model and commit the new tapes.
"""

import pytest

from evals import invoices, policy, whatsapp
from evals.common import RECORDINGS, Models
from evals.tape import ReplayCompletion, ReplayEmbedding, Tape

SUITES = {whatsapp.SUITE: whatsapp, invoices.SUITE: invoices, policy.SUITE: policy}


@pytest.mark.parametrize("name", SUITES)
async def test_the_replayed_score_matches_the_recorded_one(name: str) -> None:
    tape = Tape.load(RECORDINGS / f"{name}.json")
    chat, embedding = ReplayCompletion(tape), ReplayEmbedding(tape)
    report = await SUITES[name].run(Models(chat, embedding))
    assert chat.misses + embedding.misses == [], (
        "the tape is out of date: record it again with the real model"
    )
    assert report.summary == tape.expected_summary
