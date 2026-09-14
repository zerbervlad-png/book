"""Check-ins API — sections 11, 29, 30, 49.

QR / barcode / token / code / manual / API. GPS accepted as auxiliary only.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines import checkin as checkin_engine
from app.engines import fraud
from app.models import CheckInMethod, Event, Resource, User
from app.schemas import CheckInRequest, CheckInOut

router = APIRouter(prefix="/checkins", tags=["checkins"])


@router.post("", response_model=CheckInOut)
def perform_checkin(payload: CheckInRequest, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Self check-in (e.g. physical queue — 30) or operator scan.
    Only the right's owner, the event organizer or an admin may submit a
    check-in — otherwise any user could burn someone else's token."""
    try:
        method = CheckInMethod(payload.method)
    except ValueError:
        raise HTTPException(400, f"Invalid method; allowed: {[m.value for m in CheckInMethod]}")

    from app.models import AccessRight
    probe = db.scalar(select(AccessRight).where(AccessRight.token_code == payload.token.strip()))
    if probe is not None:
        is_owner = probe.owner_user_id == user.id
        is_organizer = probe.resource.event.organizer_id is not None and \
            probe.resource.event.organizer.user_id == user.id
        is_admin = user.role.value == "ADMIN"
        if not (is_owner or is_organizer or is_admin):
            raise HTTPException(403, "Only the owner, the event organizer or an admin "
                                     "can check in this token")

    if payload.gps:
        # 10 / 49 / 65: auxiliary signal, never a proof
        fraud.record_gps_telemetry(
            db, user.id, payload.gps.get("lat"), payload.gps.get("lng"),
            payload.gps.get("accuracy_m"), payload.gps.get("event_id"))

    result, record, right = checkin_engine.check_in(
        db, payload.token, method, checked_by_user_id=user.id, gps=payload.gps or None)
    db.commit()
    if record:
        db.refresh(record)
        return record
    raise HTTPException(500, "Check-in recording failed")


@router.get("/event/{event_id}", response_model=list[CheckInOut])
def event_checkins(event_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    is_organizer = event.organizer and event.organizer.user_id == user.id
    if not is_organizer and user.role.value != "ADMIN":
        raise HTTPException(403, "Only the organizer can view check-ins")
    from app.models import CheckIn
    return db.scalars(select(CheckIn).where(CheckIn.event_id == event_id)
                      .order_by(CheckIn.checked_at.desc())).all()
