"""Find the policy rules closest in meaning to a question (decision 043).

The question is embedded with the same model that embedded the rules, and Postgres (pgvector)
orders the rules by cosine distance: 0 is the same direction, 1 is unrelated. The score shown
is 1 minus that distance. Scores of one model are only comparable with each other: they say
which rule is closest, not how "true" a match is, so the caller always gets the closest few.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PolicyRule
from app.llm.embeddings import Embedder


class PolicyNeedsReembedding(Exception):
    """The stored rules were embedded by another model than the one now configured, so their
    vectors can't be compared with the question's. Uploading the policy again fixes it."""

    def __init__(self, stored: list[str], current: str) -> None:
        super().__init__(
            f"The policy was embedded with {', '.join(stored)}, but search now uses {current}. "
            "Upload the policy again to embed it with the current model."
        )


@dataclass(frozen=True)
class PolicyHit:
    rule: PolicyRule
    score: float  # cosine similarity, 1 = same direction


@dataclass(frozen=True)
class PolicySearch:
    query: str
    embedding_model: str | None  # None: there is no policy to search yet
    hits: list[PolicyHit]


async def search_policy(
    session: AsyncSession, question: str, embed: Embedder, *, limit: int = 3
) -> PolicySearch:
    stored = list(await session.scalars(select(PolicyRule.embedding_model).distinct()))
    if not stored:
        return PolicySearch(question, None, [])
    embedded = await embed([question], "query")
    if stored != [embedded.model]:
        raise PolicyNeedsReembedding(sorted(stored), embedded.model)
    distance = PolicyRule.embedding.cosine_distance(embedded.vectors[0]).label("distance")
    rows = await session.execute(select(PolicyRule, distance).order_by(distance).limit(limit))
    hits = [PolicyHit(rule, round(1 - float(d), 4)) for rule, d in rows.all()]
    return PolicySearch(question, embedded.model, hits)


@dataclass(frozen=True)
class RuleText:
    code: str
    section_title: str
    text: str


async def rule_texts(session: AsyncSession) -> dict[str, RuleText]:
    """Every stored rule's wording by its number, for showing next to a citation (no vectors
    are loaded)."""
    rows = await session.execute(select(PolicyRule.code, PolicyRule.section_title, PolicyRule.text))
    return {code: RuleText(code, title, text) for code, title, text in rows.all()}
