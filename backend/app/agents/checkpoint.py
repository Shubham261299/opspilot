"""Where paused agents are kept: LangGraph's Postgres checkpointer.

A checkpoint is a saved copy of a graph's state after each step. A graph waiting at
interrupt() for a human is just its latest checkpoint, so it survives a server restart and
can be resumed later by any process.

The checkpointer manages its own tables with setup(). They live in a separate `langgraph`
schema so they never mix with the app's tables, which Alembic owns. It talks to Postgres
through psycopg (the app itself uses asyncpg).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

SCHEMA = "langgraph"


def psycopg_url(database_url: str) -> str:
    """postgresql+asyncpg://... (SQLAlchemy) -> postgresql://... (psycopg)."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


@asynccontextmanager
async def open_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    url = psycopg_url(database_url)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    async with AsyncConnectionPool(
        url,
        min_size=1,
        max_size=4,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "options": f"-c search_path={SCHEMA}"},
    ) as pool:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()  # creates or upgrades its tables; safe to run every start
        yield saver
