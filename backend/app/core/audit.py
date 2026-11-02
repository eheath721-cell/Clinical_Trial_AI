from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.crypto import hash_ip
from app.models import AuditEvent

# Keys that may appear in audit metadata. Anything else is dropped so clinical values or
# free text can never leak into the audit trail by accident.
_ALLOWED_META = {"count", "doc_type", "fact_type", "status", "classification", "source", "reason", "nct_id", "role"}


def record(
    db: Session,
    action: str,
    *,
    actor_id: uuid.UUID | None,
    request: Request | None = None,
    resource_type: str | None = None,
    resource_id: str | uuid.UUID | None = None,
    profile_id: uuid.UUID | None = None,
    outcome: str = "success",
    meta: dict[str, Any] | None = None,
) -> None:
    ip = request.client.host if request is not None and request.client else None
    safe_meta = {k: v for k, v in (meta or {}).items() if k in _ALLOWED_META} or None
    db.add(
        AuditEvent(
            actor_user_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            profile_id=profile_id,
            ip_hash=hash_ip(ip),
            outcome=outcome,
            meta=safe_meta,
        )
    )
