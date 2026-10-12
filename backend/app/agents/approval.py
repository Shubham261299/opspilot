"""The approval agent: one small LangGraph graph per proposal.

    START -> explain -> wait -> apply -> END
                         ^        |
                         +--------+  (apply refused, e.g. "order not ready": wait again)

- explain: the language model words the proposal for the owner (and drafts a reminder's
  message to the customer). Code checks the text: any number that isn't among the figures
  code computed, or another customer's name in a reminder, and the text is thrown away and
  the template reason is used instead (CLAUDE.md rule 3).
- wait: interrupt() pauses the graph. Its state is saved in Postgres (agents/checkpoint.py)
  and nothing happens until a human clicks Approve or Reject, which resumes this graph.
- apply: runs the same transactional approve/reject code as always (proposals/decisions.py:
  row lock, effect, audit row). Nothing acts without that human decision (rule 2).

If a human decides before the explanation is ready, the decision goes straight to the same
approve/reject code and the graph ends without waiting.

A restart can cut a graph off while it explains (the model takes a while). At start-up,
recover() carries such graphs on from their last checkpoint, and starts any that never ran.
"""

import logging
import uuid
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import events
from app.db.audit import OWNER
from app.db.models import Customer, CustomerOrder, Proposal
from app.domain.matching import normalise_name
from app.domain.text_numbers import unexpected_numbers
from app.intake.product_picks import Ask
from app.llm.client import LlmError
from app.llm.explain import ReminderDraft, explain_messages, schema_for
from app.proposals import decisions
from app.proposals.errors import NotReady, not_ready

logger = logging.getLogger(__name__)
Action = Literal["approve", "reject"]


class ApprovalState(TypedDict, total=False):
    proposal_id: int
    still_pending: bool
    decision: dict[str, Any]  # {"action": "approve" | "reject", "note": str | None}
    outcome: dict[str, Any]  # {"status": "approved"} or {"error": code, "message": text}


class AgentRunner:
    """Starts approval graphs for new proposals and resumes them with human decisions."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        checkpointer: BaseCheckpointSaver[Any],
        ask: Ask,
    ) -> None:
        self.sessions = sessions
        self.ask = ask  # the language model; tests swap in a fake
        graph = StateGraph(ApprovalState)
        graph.add_node("explain", self._explain)
        graph.add_node("wait", self._wait)
        graph.add_node("apply", self._apply)
        graph.add_edge(START, "explain")
        graph.add_conditional_edges(
            "explain", lambda s: "wait" if s["still_pending"] else END, ["wait", END]
        )
        graph.add_edge("wait", "apply")
        graph.add_conditional_edges("apply", self._after_apply, ["wait", END])
        self.graph = graph.compile(checkpointer=checkpointer)

    # Starting -----------------------------------------------------------------------------

    async def start_pending(self) -> int:
        """Start a graph for every pending proposal that has none yet; each runs until it
        waits for a human. Safe to call from several places at once: each proposal is
        claimed by exactly one caller."""
        started = 0
        while (claimed := await self._claim_next()) is not None:
            proposal_id, thread_id = claimed
            await self.graph.ainvoke({"proposal_id": proposal_id}, _config(thread_id))
            started += 1
        if started:
            logger.info("approval agents started", extra={"agents": started})
        return started

    async def recover(self) -> int:
        """At start-up: finish graphs a restart cut off before they reached `wait`, then
        start graphs for proposals that never got one. Returns how many were carried on."""
        async with self.sessions() as session:
            cut_off = (
                await session.execute(
                    select(Proposal.id, Proposal.agent_thread_id).where(
                        Proposal.status == "pending",
                        Proposal.agent_thread_id.is_not(None),
                        Proposal.explained_by.is_(None),  # explain never finished
                    )
                )
            ).all()
        resumed = 0
        for proposal_id, thread_id in cut_off:
            config = _config(thread_id)
            if (await self.graph.aget_state(config)).next:
                # Saved part-way: None as input means "carry on from the last checkpoint".
                try:
                    await self.graph.ainvoke(None, config)
                    resumed += 1
                except Exception:  # one broken graph mustn't stop the others
                    logger.exception(
                        "approval agent not recovered", extra={"proposal_id": proposal_id}
                    )
            else:  # nothing saved yet: let start_pending begin it again
                async with self.sessions() as session:
                    proposal = await session.get(Proposal, proposal_id)
                    if proposal is not None:
                        proposal.agent_thread_id = None
                    await session.commit()
        if cut_off:
            logger.info("approval agents recovered", extra={"agents": len(cut_off)})
        await self.start_pending()
        return resumed

    async def _claim_next(self) -> tuple[int, str] | None:
        thread_id = uuid.uuid4().hex
        async with self.sessions() as session:
            # SKIP LOCKED: two callers never claim the same proposal.
            proposal_id = await session.scalar(
                text(
                    "UPDATE proposals SET agent_thread_id = :thread WHERE id = ("
                    "  SELECT id FROM proposals"
                    "  WHERE status = 'pending' AND agent_thread_id IS NULL"
                    "  ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
                    ") RETURNING id"
                ),
                {"thread": thread_id},
            )
            await session.commit()
        return None if proposal_id is None else (proposal_id, thread_id)

    # Deciding -----------------------------------------------------------------------------

    async def decide(self, proposal_id: int, action: Action, note: str | None) -> None:
        """A human's decision. Raises the same errors as proposals/decisions.py."""
        async with self.sessions() as session:
            proposal = await session.get(Proposal, proposal_id)
            if proposal is None:
                raise decisions.ProposalNotFound(proposal_id)
            if proposal.status != "pending":
                raise decisions.ProposalNotPending(proposal.status)
            thread_id = proposal.agent_thread_id
        if thread_id is not None:
            config = _config(thread_id)
            snapshot = await self.graph.aget_state(config)
            if snapshot.next == ("wait",):  # paused, waiting for exactly this
                result = await self.graph.ainvoke(
                    Command(resume={"action": action, "note": note}), config
                )
                _raise_if_refused(result.get("outcome", {}))
                return
        # Not started, or still explaining: decide now with the same code; the graph will
        # see the proposal is decided and end without waiting.
        async with self.sessions() as session:
            decide = decisions.approve if action == "approve" else decisions.reject
            await decide(session, proposal_id, actor=OWNER, note=note)

    # The graph's steps -------------------------------------------------------------------

    async def _explain(self, state: ApprovalState) -> ApprovalState:
        async with self.sessions() as session:
            proposal = await session.get(Proposal, state["proposal_id"])
            if proposal is None or proposal.status != "pending":
                return {"still_pending": False}
            customer, others = await _customers(session, proposal)
            kind, reason, numbers = proposal.kind, proposal.reason, dict(proposal.numbers)
        written = await self._write(kind, reason, numbers, customer, others)
        async with self.sessions() as session:
            proposal = await session.get(Proposal, state["proposal_id"])
            if proposal is None:
                return {"still_pending": False}
            if written is not None:
                proposal.explanation = written.explanation
                if isinstance(written, ReminderDraft):
                    proposal.draft_message = written.customer_message
            proposal.explained_by = "llm" if written is not None else "template"
            still_pending = proposal.status == "pending"
            await session.commit()
        events.proposal_explained(state["proposal_id"])
        return {"still_pending": still_pending}

    async def _write(
        self,
        kind: str,
        reason: str,
        numbers: dict[str, Any],
        customer: str | None,
        other_customers: list[str],
    ) -> Any:
        """The model's wording, or None when it failed or broke a rule."""
        try:
            written = await self.ask(
                explain_messages(kind, reason, numbers, customer), schema_for(kind), "explain"
            )
        except LlmError:
            return None
        texts = [written.explanation]
        if isinstance(written, ReminderDraft):
            texts.append(written.customer_message)
        sources = [reason, str(numbers)]
        bad_numbers = sorted({n for t in texts for n in unexpected_numbers(t, sources)})
        named = [name for name in other_customers if any(name in normalise_name(t) for t in texts)]
        if bad_numbers or named:
            logger.warning(
                "llm explanation rejected",
                extra={"kind": kind, "new_numbers": bad_numbers, "other_customers": named},
            )
            return None
        return written

    async def _wait(self, state: ApprovalState) -> ApprovalState:
        # Pauses here. The value passed to Command(resume=...) is what interrupt() returns.
        decision = interrupt({"proposal_id": state["proposal_id"]})
        return {"decision": decision}

    async def _apply(self, state: ApprovalState) -> ApprovalState:
        decision = state["decision"]
        decide = decisions.approve if decision["action"] == "approve" else decisions.reject
        async with self.sessions() as session:
            try:
                proposal = await decide(
                    session, state["proposal_id"], actor=OWNER, note=decision.get("note")
                )
            except decisions.ProposalNotPending as exc:
                await session.rollback()
                return {"outcome": {"error": "proposal_already_decided", "message": str(exc)}}
            except NotReady as exc:
                await session.rollback()
                return {"outcome": {"error": exc.code, "message": exc.message}}
        return {"outcome": {"status": proposal.status}}

    @staticmethod
    def _after_apply(state: ApprovalState) -> str:
        # Refused because something must be fixed first: wait for the next decision.
        error = state["outcome"].get("error")
        return "wait" if error and error != "proposal_already_decided" else END


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _raise_if_refused(outcome: dict[str, Any]) -> None:
    error = outcome.get("error")
    if error == "proposal_already_decided":
        raise decisions.ProposalNotPending("decided")
    if error is not None:
        raise not_ready(error, outcome["message"])


async def _customers(session: AsyncSession, proposal: Proposal) -> tuple[str | None, list[str]]:
    """The proposal's customer's name, and every other customer's (normalised) name."""
    customer_id = proposal.customer_id
    if customer_id is None and proposal.order_id is not None:
        order = await session.get(CustomerOrder, proposal.order_id)
        customer_id = order.customer_id if order else None
    names = (await session.execute(select(Customer.id, Customer.shop_name))).all()
    own = next((name for id_, name in names if id_ == customer_id), None)
    others = [normalise_name(name) for id_, name in names if id_ != customer_id]
    return own, others
