"""Waitlists API — sections 17, 3.4."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines import waitlist as waitlist_engine
from app.models import Event, EventStatus, Resource, User, WaitlistEntry
from app.schemas import ReservationOut, WaitlistEntryOut

router = APIRouter(prefix="/waitlists", tags=["waitlists"])


def _load_resource(db: Session, resource_id: int) -> Resource:
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    if resource.event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
        raise HTTPException(409, "Event is cancelled or completed")
    return resource


@router.post("/resources/{resource_id}/join", response_model=WaitlistEntryOut, status_code=201)
def join(resource_id: int, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    resource = _load_resource(db, resource_id)
    try:
        entry = waitlist_engine.join(db, user.id, resource)
    except waitlist_engine.WaitlistError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    return entry


@router.post("/resources/{resource_id}/leave", status_code=204)
def leave(resource_id: int, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    resource = _load_resource(db, resource_id)
    try:
        waitlist_engine.leave(db, user.id, resource)
    except waitlist_engine.WaitlistError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()


@router.get("/resources/{resource_id}/me", response_model=WaitlistEntryOut | None)
def my_entry(resource_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    resource = _load_resource(db, resource_id)
    waitlist = waitlist_engine.ensure_waitlist(db, resource)
    return db.scalar(select(WaitlistEntry).where(
        WaitlistEntry.waitlist_id == waitlist.id,
        WaitlistEntry.user_id == user.id,
        WaitlistEntry.status.in_(["WAITING", "OFFERED", "CONFIRMED"])))


@router.post("/entries/{entry_id}/confirm", response_model=ReservationOut, status_code=201)
def confirm_offer(entry_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    try:
        reservation = waitlist_engine.confirm_offer(db, user.id, entry_id)
    except waitlist_engine.WaitlistError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(reservation)
    return reservation
