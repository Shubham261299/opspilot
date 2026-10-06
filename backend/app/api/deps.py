"""Shared FastAPI dependencies.

`Annotated[AsyncSession, Depends(get_session)]` tells FastAPI: "call get_session for
each request and pass its result in". Declaring it once here keeps endpoint
signatures short: `async def endpoint(session: SessionDep)`. Tests can swap any of
these for a stand-in with `app.dependency_overrides`.
"""

from datetime import date
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.approval import AgentRunner
from app.config import Settings, get_settings
from app.db.session import get_session, get_sessionmaker
from app.intake.whatsapp_orders import Ask, ask_llm


def get_today() -> date:
    """Today's date, or the pinned APP_TODAY when the demo data needs a fixed date."""
    return get_settings().app_today or date.today()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TodayDep = Annotated[date, Depends(get_today)]


def get_ask() -> Ask:
    """The language model, as a function; tests replace it with a fake one."""
    return ask_llm


AskDep = Annotated[Ask, Depends(get_ask)]


def get_agents(request: Request) -> AgentRunner:
    """The approval agents, created when the app starts (main.py lifespan)."""
    agents: AgentRunner = request.app.state.agents
    return agents


AgentsDep = Annotated[AgentRunner, Depends(get_agents)]
# For work that outlives the request (background tasks), which opens its own sessions.
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
