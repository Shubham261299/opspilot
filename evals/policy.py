"""Eval: policy search, scored against the questions in the answer key.

Runs the same code the app runs: the policy PDF is read, split into rules and embedded
(intake/policy_import.py) into a real Postgres with pgvector, then each question is searched with
`search_policy` (the function behind GET /policy/search). A question is "right" when the rule the
key names for it is the closest rule (hit@1) or among the closest three (hit@3).

The questions are a small set written by hand before the first run and not changed to suit its
results, so the numbers are rough: one question more or less moves them by several points.
"""

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.intake.policy_import import import_policy
from app.policy_search import search_policy
from evals.common import (
    DATA,
    Models,
    Report,
    eval_database_url,
    load_answer_key,
    prepare_database,
)

SUITE = "policy"
LIMIT = 3


async def run(models: Models) -> Report:
    questions = load_answer_key()["policy_questions"]
    url = eval_database_url()
    await prepare_database(url)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            imported = await import_policy(
                session,
                filename="company_policy.pdf",
                content=(DATA / "company_policy.pdf").read_bytes(),
                embed=models.embed,
                actor="eval",
            )
            rows = []
            for item in questions:
                found = await search_policy(session, item["question"], models.embed, limit=LIMIT)
                rows.append(
                    {
                        "question": item["question"],
                        "language": item["language"],
                        "expected": item["expected"],
                        "got": [hit.rule.code for hit in found.hits],
                        "scores": [hit.score for hit in found.hits],
                    }
                )
    finally:
        await engine.dispose()
    return Report(summarise(rows, imported.rules_loaded, models.counted_embedding.calls), rows)


def summarise(
    rows: list[dict[str, Any]], rules_loaded: int, embedding_calls: int
) -> dict[str, Any]:
    def count(language: str | None, *, top: int) -> int:
        return sum(
            r["expected"] in r["got"][:top] for r in rows if language in (None, r["language"])
        )

    def total(language: str) -> int:
        return sum(1 for r in rows if r["language"] == language)

    return {
        "embedding_calls": embedding_calls,
        "rules_loaded": rules_loaded,
        "questions": len(rows),
        "hit_at_1": count(None, top=1),
        "hit_at_3": count(None, top=3),
        "english_questions": total("en"),
        "english_hit_at_1": count("en", top=1),
        "english_hit_at_3": count("en", top=3),
        "hinglish_questions": total("hinglish"),
        "hinglish_hit_at_1": count("hinglish", top=1),
        "hinglish_hit_at_3": count("hinglish", top=3),
        "missed_at_1": [
            f"{r['expected']} expected, closest {r['got'][0]}: {r['question']}"
            for r in rows
            if r["got"][0] != r["expected"]
        ],
    }
