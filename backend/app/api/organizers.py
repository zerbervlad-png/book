"""Organizers API — sections 23, 37, 58."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_organizer_profile, require_organizer
from app.core.database import get_db
from app.engines import verification as verification_engine
from app.models import Event, Organizer, User, UserRole
from app.schemas import EventOut, OrganizerCreate, OrganizerOut

router = APIRouter(prefix="/organizers", tags=["organizers"])


@router.post("", response_model=OrganizerOut, status_code=201)
def become_organizer(payload: OrganizerCreate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Any authenticated user can register an organizer profile (self-service);
    organizer verification (Organizer Verified, section 6) stays admin-controlled."""
    if db.scalar(select(Organizer).where(Organizer.user_id == user.id)):
        raise HTTPException(409, "Already an organizer")
    organizer = Organizer(user_id=user.id, name=payload.name, description=payload.description)
    db.add(organizer)
    if user.role == UserRole.USER:
        user.role = UserRole.ORGANIZER
    db.flush()
    db.commit()
    db.refresh(organizer)
    return organizer


@router.get("/me", response_model=OrganizerOut)
def my_organizer(db: Session = Depends(get_db), user: User = Depends(require_organizer)):
    return get_organizer_profile(db, user)


@router.get("/me/events", response_model=list[EventOut])
def my_events(db: Session = Depends(get_db), user: User = Depends(require_organizer)):
    organizer = get_organizer_profile(db, user)
    events = db.scalars(select(Event).where(Event.organizer_id == organizer.id)).all()
    return events


@router.post("/verify/{organizer_id}", response_model=OrganizerOut)
def verify_organizer(organizer_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    if user.role.value != "ADMIN":
        raise HTTPException(403, "Admin only")
    organizer = db.get(Organizer, organizer_id)
    if not organizer:
        raise HTTPException(404, "Organizer not found")
    verification_engine.verify_organizer(db, organizer, actor_user_id=user.id)
    db.commit()
    return organizer
