"""Events API — sections 4, 5, 6, 7, 20-22, 35, 36, 53, 69, 70.

Events exist before physical occurrence; creation via organizer (5.1),
import (5.2) and user request (5.3). Verification via the separate
Event Verification Engine (7).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user
from app.core.database import get_db
from app.engines import verification as verification_engine
from app.engines.availability import compute_event_inventory
from app.engines.audit import audit
from app.models import (
    AuditEventType, Event, EventSource, EventStatus, EventVerification as VerificationRecord,
    Organizer, Resource, User,
)
from app.schemas import (
    EventCreate, EventInventoryOut, EventOut, EventVerificationOut, ResourceOut,
)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventOut, status_code=201)
def create_event(payload: EventCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    starts_at = payload.starts_at
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)  # 36: timezone handling

    organizer = db.scalar(select(Organizer).where(Organizer.user_id == user.id))
    if user.role.value == "ORGANIZER" and organizer:
        source = EventSource.ORGANIZER
    elif payload.source_url:
        source = EventSource.IMPORT  # 5.2: import from official source
    else:
        source = EventSource.USER_REQUEST  # 5.3: user proposal

    organizer_name = organizer.name if organizer else None
    key = verification_engine.canonical_key(
        payload.title, payload.city, starts_at, organizer_name)

    # 69: duplicate detection
    duplicate = verification_engine.find_duplicate(db, key)
    if duplicate:
        raise HTTPException(409, detail={
            "code": "DUPLICATE_EVENT",
            "message": "Event already exists",
            "event_id": duplicate.id,
        })

    event = Event(
        title=payload.title,
        description=payload.description,
        image_url=payload.image_url,
        starts_at=starts_at,
        ends_at=payload.ends_at,
        timezone_name=payload.timezone_name,
        city=payload.city,
        address=payload.address,
        lat=payload.lat,
        lng=payload.lng,
        organizer_id=organizer.id if organizer and user.role.value == "ORGANIZER" else None,
        capacity=payload.capacity,
        category=payload.category,
        source=source,
        source_url=payload.source_url,
        status=EventStatus.PENDING_VERIFICATION,
        created_by_user_id=user.id,
        canonical_key=key,
    )
    db.add(event)
    db.flush()
    audit(db, AuditEventType.EVENT_CREATED, "Event", event.id, actor_user_id=user.id,
          source=source.value)
    db.commit()
    db.refresh(event)
    return event


@router.get("", response_model=list[EventOut])
def search_events(
    q: str | None = None,
    category: str | None = None,
    city: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    verified_only: bool = False,
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    stmt = select(Event)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(Event.title.ilike(like), Event.description.ilike(like)))
    if category:
        stmt = stmt.where(Event.category == category)
    if city:
        stmt = stmt.where(Event.city == city)
    if date_from:
        stmt = stmt.where(Event.starts_at >= date_from)
    if date_to:
        stmt = stmt.where(Event.starts_at <= date_to)
    if verified_only:
        stmt = stmt.where(Event.verification_status.in_(
            ["VERIFIED", "ORGANIZER_VERIFIED", "OFFICIAL"]))
    if status:
        stmt = stmt.where(Event.status == status)
    stmt = stmt.order_by(Event.starts_at).limit(limit).offset(offset)
    return db.scalars(stmt).all()


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return event


@router.get("/{event_id}/resources", response_model=list[ResourceOut])
def event_resources(event_id: int, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return db.scalars(select(Resource).where(Resource.event_id == event_id)).all()


@router.get("/{event_id}/inventory", response_model=EventInventoryOut)
def event_inventory(event_id: int, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return compute_event_inventory(db, event)


@router.get("/{event_id}/verifications", response_model=list[EventVerificationOut])
def event_verifications(event_id: int, db: Session = Depends(get_db)):
    return db.scalars(select(VerificationRecord).where(
        VerificationRecord.event_id == event_id).order_by(
        VerificationRecord.checked_at.desc())).all()


@router.post("/{event_id}/verify", response_model=EventOut)
def verify_event(event_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    is_admin = user.role.value == "ADMIN"
    is_own_organizer = event.organizer and event.organizer.user_id == user.id
    if not (is_admin or is_own_organizer):
        raise HTTPException(403, "Only admin or the event organizer can trigger verification")
    verification_engine.run_verification(db, event, actor_user_id=user.id)
    db.commit()
    db.refresh(event)
    return event


@router.post("/{event_id}/cancel", response_model=EventOut)
def cancel_event(event_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    is_admin = user.role.value == "ADMIN"
    is_own_organizer = event.organizer and event.organizer.user_id == user.id
    if not (is_admin or is_own_organizer):
        raise HTTPException(403, "Only admin or the event organizer can cancel")
    event.status = EventStatus.CANCELLED
    audit(db, AuditEventType.EVENT_CANCELLED, "Event", event.id, actor_user_id=user.id)
    db.commit()
    db.refresh(event)
    return event
