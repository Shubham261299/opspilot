"""FastAPI application: wiring only (logging, middleware, error handlers, routers)."""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.agents.approval import AgentRunner
from app.agents.checkpoint import open_checkpointer
from app.api import customers, health, issues, orders, products, proposals, uploads
from app.api.errors import error_response, register_error_handlers
from app.config import get_settings
from app.db.session import get_engine, get_sessionmaker
from app.intake.whatsapp_import import fail_interrupted_uploads
from app.intake.whatsapp_orders import ask_llm
from app.logging_config import new_request_id, request_id_var, setup_logging

setup_logging(get_settings().log_level)
logger = logging.getLogger("app.request")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # A chat being read when the server stopped will never finish: say so instead of
    # leaving it "processing" for ever.
    await fail_interrupted_uploads()
    # Paused approval agents live in Postgres; open the checkpointer once for the app's life.
    async with open_checkpointer(get_settings().database_url) as checkpointer:
        app.state.agents = AgentRunner(get_sessionmaker(), checkpointer, ask_llm)
        yield
    await get_engine().dispose()  # close pooled connections on shutdown


app = FastAPI(title="OpsPilot API", version="0.1.0", lifespan=lifespan)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(uploads.router)
app.include_router(products.router)
app.include_router(issues.router)
app.include_router(customers.router)
app.include_router(proposals.router)
app.include_router(orders.router)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Give every request an id (in logs and the X-Request-ID header) and log it once."""
    request_id = new_request_id(request.headers.get("x-request-id"))
    request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error", extra={"path": request.url.path})
        response = error_response(500, "internal_error", "Something went wrong on our side.")
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response
