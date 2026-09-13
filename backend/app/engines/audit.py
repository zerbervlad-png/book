"""Audit engine — sections 32, 33. Append-only server-side audit trail."""
from sqlalchemy.orm import Session

from app.models import AuditEvent, AuditEventType, utcnow


def audit(
    db: Session,
    event_type: AuditEventType,
    entity_type: str,
    entity_id,
    actor_user_id: int | None = None,
    **data,
) -> AuditEvent:
    record = AuditEvent(
        type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        actor_user_id=actor_user_id,
        data=data or {},
        created_at=utcnow(),
    )
    db.add(record)
    return record
