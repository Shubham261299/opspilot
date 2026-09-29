"""Building audit_log rows: who did what, to which record, when, and the before/after state."""

from typing import Any

from app.db.models import AuditLog
from app.logging_config import request_id_var

# No sign-in yet, so every action is recorded as the shop owner's.
OWNER = "owner"


def audit_entry(
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: int | str | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """An audit row, linked to the current request's log lines through its request id."""
    return AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        before=before,
        after=after,
        request_id=request_id_var.get(),
    )
