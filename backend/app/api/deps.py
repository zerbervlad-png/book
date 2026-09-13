"""Auth dependencies."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import Organizer, User, UserRole


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_access_token(auth.removeprefix("Bearer ").strip())
    if payload is None:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, "User not found or blocked")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        return None
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def require_organizer(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.ORGANIZER, UserRole.ADMIN):
        raise HTTPException(403, "Organizer role required")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Admin role required")
    return user


def get_organizer_profile(db: Session, user: User) -> Organizer:
    organizer = db.query(Organizer).filter(Organizer.user_id == user.id).first()
    if organizer is None:
        raise HTTPException(403, "Organizer profile not found")
    return organizer
