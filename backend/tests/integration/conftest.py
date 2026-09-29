"""Integration tests run against a real Postgres database, never the dev database.

Locally: start the Docker database first (`docker compose up -d db`); the test
database `opspilot_test` is created on that server automatically.
In CI: TEST_DATABASE_URL points at the Postgres service container.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.db.models import Base

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://opspilot:opspilot@localhost:5433/opspilot_test"
BACKEND_DIR = Path(__file__).resolve().parents[2]


async def _recreate_schema(database_url: str) -> None:
    """Create the test database if it's missing, then empty it completely."""
    url = make_url(database_url)
    admin = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    await admin.dispose()

    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    """URL of an empty, fully migrated test database (prepared once per test run)."""
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.exit(
            f"Refusing to use database {database!r}: tests wipe it, so its name must end in _test."
        )
    try:
        asyncio.run(_recreate_schema(url))
    except (OSError, SQLAlchemyError) as exc:
        shown = make_url(url).render_as_string(hide_password=True)
        pytest.fail(
            f"Can't reach the test database at {shown}. "
            f"Start it with `docker compose up -d db`. ({exc})",
            pytrace=False,
        )
    command.upgrade(_alembic_config(url), "head")
    return url


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def alembic_cfg(database_url: str) -> Config:
    return _alembic_config(database_url)


@pytest.fixture
async def db_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine for one test. Every table is emptied first, so tests can't affect each other."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        yield session
