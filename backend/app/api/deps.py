"""Shared FastAPI dependencies.

`Annotated[AsyncSession, Depends(get_session)]` tells FastAPI: "call get_session for
each request and pass its result in". Declaring it once here keeps endpoint
signatures short: `async def endpoint(session: SessionDep)`.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
