"""Integration tests run against a real Postgres database, never the dev database.

Locally: start the Docker database first (`docker compose up -d db`); the test
database `opspilot_test` is created on that server automatically.
In CI: TEST_DATABASE_URL points at the Postgres service container.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.agents.approval import AgentRunner
from app.agents.checkpoint import open_checkpointer
from app.db.models import Base
from app.db.seed import ProductRow, SupplierRow, read_csv_rows, seed_reference_data
from app.llm.client import LlmError

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://opspilot:opspilot@localhost:5433/opspilot_test"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_TODAY = date(2026, 9, 29)

# The app reads DATABASE_URL at import; make sure it can only ever see the test database.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


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
    url = TEST_DATABASE_URL
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


@pytest.fixture
async def seeded(db_session: AsyncSession, sample_data_dir: Path) -> None:
    """The 6 suppliers and 60 products from the sample CSVs."""
    await seed_reference_data(
        db_session,
        read_csv_rows(sample_data_dir / "suppliers.csv", SupplierRow),
        read_csv_rows(sample_data_dir / "product_master.csv", ProductRow),
    )


class ModelUnavailable:
    """The default "language model" in tests: never reachable, so the code's own fallbacks
    (template explanations) are used. Tests that need answers set agents.ask to a fake."""

    async def __call__(self, messages: object, schema: object, purpose: str) -> object:
        raise LlmError("unavailable", "no language model in tests")


@pytest.fixture
async def agents(db_engine: AsyncEngine) -> AsyncIterator[AgentRunner]:
    """Approval agents with a real Postgres checkpointer on the test database."""
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with open_checkpointer(TEST_DATABASE_URL) as checkpointer:
        yield AgentRunner(sessions, checkpointer, ModelUnavailable())


@pytest.fixture
async def client(db_engine: AsyncEngine, agents: AgentRunner) -> AsyncIterator[AsyncClient]:
    """An HTTP client that calls the app directly (no server), using the test database.

    httpx's ASGITransport hands each request straight to the FastAPI app in this process.
    """
    from app.api.deps import get_agents, get_today
    from app.db.session import get_session, get_sessionmaker
    from app.main import app  # imported here, after DATABASE_URL points at the test database

    sessions = async_sessionmaker(db_engine, expire_on_commit=False)

    async def test_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_sessionmaker] = lambda: sessions  # for background tasks
    app.dependency_overrides[get_agents] = lambda: agents
    app.dependency_overrides[get_today] = lambda: TEST_TODAY
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()
