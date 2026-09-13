"""Notifications API — section 44."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Notification, User
from app.schemas import NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def my_notifications(unread_only: bool = False, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return db.scalars(stmt.order_by(Notification.created_at.desc()).limit(100)).all()


@router.post("/{notification_id}/read", status_code=204)
def mark_read(notification_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    notification = db.get(Notification, notification_id)
    if notification and notification.user_id == user.id:
        notification.is_read = True
        db.commit()
