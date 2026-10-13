"""Optional tracing of model calls in Langfuse.

LiteLLM can tell a "callback" about every call it makes. The `langfuse_otel` callback turns each
call into an OpenTelemetry span (prompt, answer, tokens, timing) and sends it to Langfuse in the
background, in batches. Tracing is observation only: if Langfuse is unreachable or misconfigured,
the span is dropped (and a warning logged) and the model call itself is unaffected.

With no Langfuse keys in the settings this module does nothing.
"""

import asyncio
import logging
import os

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_CALLBACK = "langfuse_otel"


def setup_tracing(settings: Settings | None = None) -> bool:
    """Turn tracing on when Langfuse keys are configured. Safe to call more than once.

    Returns True when tracing is active. Never raises: a broken tracing setup is logged and
    the app runs without it.
    """
    settings = settings or get_settings()
    if not settings.langfuse_enabled:
        return False
    try:
        # The callback reads its keys from the environment, not from our settings object.
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key or ""
        os.environ["LANGFUSE_SECRET_KEY"] = (
            settings.langfuse_secret_key.get_secret_value() if settings.langfuse_secret_key else ""
        )
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host
        import litellm

        if _CALLBACK not in litellm.callbacks:
            litellm.callbacks.append(_CALLBACK)
    except Exception:  # missing OpenTelemetry package, bad config: keep the app running
        logger.warning("tracing could not be turned on", exc_info=True)
        return False
    logger.info("tracing on", extra={"langfuse_host": settings.langfuse_host})
    return True


def trace_metadata(purpose: str, attempt: int) -> dict[str, object]:
    """What Langfuse shows for a call: its name, tags to filter by, and which attempt it was.

    `purpose` is e.g. "whatsapp_orders"; attempt 2 is the repair retry (see client.py).
    """
    return {
        "generation_name": purpose,
        "trace_name": purpose,
        "tags": [purpose, f"attempt-{attempt}"],
        "trace_metadata": {"purpose": purpose, "attempt": attempt},
    }


async def flush_tracing(wait_s: float = 1.0) -> None:
    """Send pending traces now. For short-lived scripts (smoke test, evals), not for the server.

    LiteLLM reports a finished call from a background task, and the exporter sends spans in
    batches every few seconds, so a script that ends right after its last call would lose the
    trace. This waits a moment for the report, then flushes the exporter. It relies on LiteLLM
    internals, so any failure is logged and ignored: it can only ever cost a trace.
    """
    import litellm

    if _CALLBACK not in (litellm.callbacks or []):
        return
    try:
        await asyncio.sleep(wait_s)
        from litellm.litellm_core_utils.litellm_logging import _in_memory_loggers

        for callback in list(_in_memory_loggers):
            provider = getattr(callback, "_tracer_provider", None)
            if provider is not None and hasattr(provider, "force_flush"):
                await asyncio.to_thread(provider.force_flush, 10_000)
    except Exception:
        logger.warning("tracing could not be flushed", exc_info=True)
