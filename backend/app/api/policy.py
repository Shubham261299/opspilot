from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import EmbedderDep, SessionDep
from app.api.errors import ApiError
from app.api.schemas import PolicyOut, PolicyRuleOut, PolicySearchHitOut, PolicySearchOut
from app.db.models import PolicyRule
from app.llm.client import LlmError
from app.policy_search import PolicyNeedsReembedding, search_policy

router = APIRouter(prefix="/policy", tags=["policy"])


@router.get("")
async def get_policy(session: SessionDep) -> PolicyOut:
    """The stored company policy: every numbered rule, in order. Empty until it is uploaded."""
    rules = (
        await session.scalars(select(PolicyRule).order_by(PolicyRule.section_no, PolicyRule.id))
    ).all()
    return PolicyOut(
        items=[_rule_out(rule) for rule in rules],
        embedding_model=rules[0].embedding_model if rules else None,
        uploaded_at=rules[0].created_at if rules else None,
    )


@router.get(
    "/search",
    responses={
        409: {"description": "The policy was embedded with another model; upload it again"},
        503: {"description": "The embedding model could not be reached"},
    },
)
async def search_the_policy(
    session: SessionDep,
    embed: EmbedderDep,
    q: Annotated[str, Query(min_length=3, max_length=300, description="A question in words")],
    limit: Annotated[int, Query(ge=1, le=10)] = 3,
) -> PolicySearchOut:
    """The rules closest in meaning to the question, closest first. `score` is cosine
    similarity: it ranks the rules, it is not a probability that the rule answers the question."""
    try:
        found = await search_policy(session, q, embed, limit=limit)
    except PolicyNeedsReembedding as exc:
        raise ApiError(409, "policy_needs_reembedding", str(exc)) from exc
    except LlmError as exc:
        raise ApiError(503, "embedding_unavailable", exc.message) from exc
    return PolicySearchOut(
        query=found.query,
        embedding_model=found.embedding_model,
        items=[
            PolicySearchHitOut(**_rule_out(hit.rule).model_dump(), score=hit.score)
            for hit in found.hits
        ],
    )


def _rule_out(rule: PolicyRule) -> PolicyRuleOut:
    return PolicyRuleOut(
        code=rule.code,
        section_no=rule.section_no,
        section_title=rule.section_title,
        text=rule.text,
    )
