"""Resources API — sections 3, 39, 40, 54, 55."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines.availability import compute_resource_availability
from app.models import Event, Resource, ResourceType, User
from app.schemas import AvailabilityOut, ResourceCreate, ResourceOut

router = APIRouter(prefix="/resources", tags=["resources"])

VALID_TYPES = {t.value for t in ResourceType}


@router.post("", response_model=ResourceOut, status_code=201)
def create_resource(payload: ResourceCreate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    event = db.get(Event, payload.event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    if not (event.organizer and event.organizer.user_id == user.id) \
            and user.role.value != "ADMIN":
        raise HTTPException(403, "Only the event organizer can add resources")
    if payload.type not in VALID_TYPES:
        raise HTTPException(400, f"Invalid resource type; allowed: {sorted(VALID_TYPES)}")
    resource = Resource(
        event_id=payload.event_id,
        type=ResourceType(payload.type),
        name=payload.name,
        capacity=payload.capacity,
        queue_policy=payload.queue_policy,
        is_transferable=payload.is_transferable,
        is_resellable=payload.is_resellable,
        requires_verification=payload.requires_verification,
        requires_check_in=payload.requires_check_in,
        requires_organizer_approval=payload.requires_organizer_approval,
        requires_physical_presence=payload.requires_physical_presence,
        refund_policy=payload.refund_policy,
        expiration_policy_seconds=payload.expiration_policy_seconds,
        max_resale_price=payload.max_resale_price,
        fee_percent=payload.fee_percent,
        price_base=payload.price_base,
        payload=payload.payload,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)
    return resource


@router.get("/{resource_id}", response_model=ResourceOut)
def get_resource(resource_id: int, db: Session = Depends(get_db)):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    return resource


@router.get("/{resource_id}/availability", response_model=AvailabilityOut)
def resource_availability(resource_id: int, db: Session = Depends(get_db)):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    return compute_resource_availability(db, resource)
