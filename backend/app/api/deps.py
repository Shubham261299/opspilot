"""Shared FastAPI dependencies.

`Annotated[AsyncSession, Depends(get_session)]` tells FastAPI: "call get_session for
each request and pass its result in". Declaring it once here keeps endpoint
signatures short: `async def endpoint(session: SessionDep)`. Tests can swap any of
these for a stand-in with `app.dependency_overrides`.
"""

from datetime import date
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session


def get_today() -> date:
    """Today's date, or the pinned APP_TODAY when the demo data needs a fixed date."""
    return get_settings().app_today or date.today()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TodayDep = Annotated[date, Depends(get_today)]
