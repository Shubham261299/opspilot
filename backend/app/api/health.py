import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import SessionDep

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unreachable"]


@router.get("/health", response_model=HealthOut)
async def health(session: SessionDep, response: Response) -> HealthOut:
    """API is up, plus one database round trip. Returns 503 if the database is unreachable."""
    try:
        async with asyncio.timeout(3):
            await session.execute(text("SELECT 1"))
    except Exception:  # any failure means "not healthy"; the log keeps the detail
        logger.warning("health check: database unreachable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthOut(status="degraded", database="unreachable")
    return HealthOut(status="ok", database="ok")
