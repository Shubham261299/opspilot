"""Approval agents: explain -> wait (interrupt) -> apply, with a real Postgres checkpointer
and a fake language model."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.approval import AgentRunner
from app.agents.checkpoint import open_checkpointer
from app.db.models import PaymentReminder, Proposal
from app.llm.explain import Explanation, ReminderDraft
from app.proposals.checks import run_checks
from tests.integration.conftest import TEST_DATABASE_URL, ModelUnavailable
from tests.integration.test_api import upload_form


class Writer:
    """A fake model that writes the given explanation (and message, for reminders)."""

    def __init__(self, explanation: str, message: str = "") -> None:
        self.explanation, self.message = explanation, message

    async def __call__(self, messages: Any, schema: type[BaseModel], purpose: str) -> Any:
        if schema is ReminderDraft:
            return ReminderDraft(explanation=self.explanation, customer_message=self.message)
        return Explanation(explanation=self.explanation)


@pytest.fixture
async def dues(client: AsyncClient, sample_data_dir: Path) -> AsyncClient:
    """Customers and the dues sheet: running checks gives reminders and holds."""
    for path, name in [
        ("/uploads/customers", "customers.xlsx"),
        ("/uploads/dues", "outstanding_dues.xlsx"),
    ]:
        content = (sample_data_dir / name).read_bytes()
        assert (await client.post(path, files=upload_form(name, content))).status_code == 201
    from app.api.deps import get_today
    from app.main import app

    app.dependency_overrides[get_today] = lambda: date(2026, 9, 24)
    return client


async def reminder(client: AsyncClient, code: str = "CUS001") -> dict[str, Any]:
    items = (await client.get("/proposals")).json()["items"]
    return next(
        p for p in items if p["kind"] == "payment_reminder" and p["subject"]["code"] == code
    )


async def test_each_new_proposal_gets_an_agent_that_waits_for_a_human(
    dues: AsyncClient, agents: AgentRunner, db_session: AsyncSession
) -> None:
    await dues.post("/proposals/run")  # agents start in the background, then pause

    proposals = (await db_session.scalars(select(Proposal))).all()
    assert proposals and all(p.agent_thread_id for p in proposals)
    for proposal in proposals:
        state = await agents.graph.aget_state(
            {"configurable": {"thread_id": proposal.agent_thread_id}}
        )
        assert state.next == ("wait",)  # paused at interrupt()
    # No model in this test, so every proposal keeps the template reason.
    assert {p.explained_by for p in proposals} == {"template"}


async def test_approving_resumes_the_agent_which_applies_the_decision(
    dues: AsyncClient, agents: AgentRunner
) -> None:
    await dues.post("/proposals/run")
    proposal = await reminder(dues)

    response = await dues.post(f"/proposals/{proposal['id']}/approve", json={"note": "ok"})

    assert response.json()["status"] == "approved"
    async with agents.sessions() as session:
        saved = await session.get(Proposal, proposal["id"])
    assert saved is not None and saved.agent_thread_id is not None
    thread = saved.agent_thread_id
    state = await agents.graph.aget_state({"configurable": {"thread_id": thread}})
    assert state.next == () and state.values["outcome"] == {"status": "approved"}
    assert state.values["decision"] == {"action": "approve", "note": "ok"}


async def test_a_checked_llm_explanation_and_reminder_are_used(
    dues: AsyncClient, agents: AgentRunner, db_session: AsyncSession
) -> None:
    agents.ask = Writer(
        "Ramesh Electricals owes ₹25,500; bill ST/5104 is 23 days overdue.",
        "Namaste Ramesh ji, bill ST/5104 of ₹19,500 is pending. Kindly pay when you can.",
    )
    await dues.post("/proposals/run")
    proposal = await reminder(dues)
    assert (proposal["explained_by"], proposal["explanation"]) == (
        "llm",
        "Ramesh Electricals owes ₹25,500; bill ST/5104 is 23 days overdue.",
    )

    await dues.post(f"/proposals/{proposal['id']}/approve")

    sent = await db_session.scalar(select(PaymentReminder))
    assert sent is not None and sent.message.startswith("Namaste Ramesh ji, bill ST/5104")


@pytest.mark.parametrize(
    ("explanation", "message"),
    [
        ("Ramesh owes about ₹26,000.", "Namaste ji, please pay."),  # a rounded, new number
        (
            "Ramesh owes ₹25,500.",
            "Namaste ji, like Om Sai Hardware, please pay.",
        ),  # another customer
    ],
    ids=["new number", "other customer"],
)
async def test_llm_text_that_breaks_the_rules_is_replaced_by_the_template(
    dues: AsyncClient, agents: AgentRunner, explanation: str, message: str
) -> None:
    agents.ask = Writer(explanation, message)
    await dues.post("/proposals/run")
    proposal = await reminder(dues)
    assert (proposal["explained_by"], proposal["explanation"], proposal["draft_message"]) == (
        "template",
        None,
        None,
    )


async def test_a_paused_agent_survives_a_restart(dues: AsyncClient, db_engine: AsyncEngine) -> None:
    await dues.post("/proposals/run")
    proposal = await reminder(dues)

    # A new runner with a new checkpointer connection: like the server after a restart.
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with open_checkpointer(TEST_DATABASE_URL) as checkpointer:
        after_restart = AgentRunner(sessions, checkpointer, ModelUnavailable())
        await after_restart.decide(proposal["id"], "reject", "paid in cash")

    rejected = (await dues.get("/proposals", params={"status": "rejected"})).json()["items"]
    assert [(p["id"], p["decision_note"]) for p in rejected] == [(proposal["id"], "paid in cash")]


async def test_a_decision_before_the_agent_started_still_works(
    dues: AsyncClient, agents: AgentRunner, db_session: AsyncSession
) -> None:
    await run_checks(db_session, today=date(2026, 9, 24), actor="owner")
    proposal = await reminder(dues)  # created without an agent (start_pending not called)

    await agents.decide(proposal["id"], "approve", None)

    assert (await reminder_status(dues, proposal["id"])) == "approved"


async def reminder_status(client: AsyncClient, proposal_id: int) -> str:
    for status in ("pending", "approved", "rejected"):
        items = (await client.get("/proposals", params={"status": status})).json()["items"]
        if any(p["id"] == proposal_id for p in items):
            return status
    return "missing"
