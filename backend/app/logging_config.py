"""Structured JSON logging with a per-request id.

Each log line is one JSON object, so logs can be filtered by field (request_id,
upload_id, ...) instead of searched as free text. The request id is kept in a
ContextVar: its value is local to the async task handling the current request,
so concurrent requests never see each other's id.
"""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
# Attributes every LogRecord has. Anything else was passed with `extra=` and becomes a field.
# uvicorn adds `color_message` (terminal colour codes) to its own records; skip it too.
_SKIPPED_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "color_message",
}


def new_request_id(incoming: str | None) -> str:
    """Reuse the caller's X-Request-ID when it is safe to log, otherwise create one."""
    if incoming and _SAFE_REQUEST_ID.fullmatch(incoming):
        return incoming
    return uuid4().hex


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _SKIPPED_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Send uvicorn's own messages through the same JSON handler.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # The request middleware already logs every request with its id.
    logging.getLogger("uvicorn.access").disabled = True
