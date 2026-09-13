"""Notification helper — section 44."""
from sqlalchemy.orm import Session

from app.models import Notification, utcnow


def notify(db: Session, user_id: int, kind: str, title: str, body: str = "", **data) -> None:
    db.add(Notification(
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        data=data or {},
        created_at=utcnow(),
    ))
