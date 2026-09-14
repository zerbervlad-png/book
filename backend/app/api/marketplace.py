"""Marketplace API — sections 20, 21, 22, 35, 51.

Universal search across events, listings, slots. The main screen is not
"queues" — it's a marketplace of limited access rights.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_optional_user
from app.core.database import get_db
from app.engines import transfer as transfer_engine
from app.engines.availability import compute_resource_availability
from app.models import Event, Listing, Resource, ResourceType
from app.schemas import (
    AvailabilityOut, EventOut, MarketplaceItemOut, PurchaseQuoteOut, ResourceOut,
    ListingOut,
)

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


@router.get("/search", response_model=list[MarketplaceItemOut])
def search(
    q: str | None = None,
    category: str | None = None,
    city: str | None = None,
    resource_type: str | None = None,
    verified_only: bool = False,
    available_only: bool = False,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    user=None,
):
    stmt = select(Event).where(Event.status.notin_(["CANCELLED", "COMPLETED", "DRAFT"]))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(Event.title.ilike(like), Event.description.ilike(like)))
    if category:
        stmt = stmt.where(Event.category == category)
    if city:
        stmt = stmt.where(Event.city == city)
    if verified_only:
        stmt = stmt.where(Event.verification_status.in_(
            ["VERIFIED", "ORGANIZER_VERIFIED", "OFFICIAL"]))
    events = db.scalars(stmt.order_by(Event.starts_at).limit(limit)).all()

    items: list[MarketplaceItemOut] = []
    for event in events:
        resources = db.scalars(select(Resource).where(Resource.event_id == event.id)).all()
        if resource_type:
            resources = [r for r in resources if r.type.value == resource_type]
        if not resources:
            items.append(MarketplaceItemOut(
                kind="EVENT", event=EventOut.model_validate(event)))
            continue
        for resource in resources:
            availability = compute_resource_availability(db, resource)
            if available_only and availability.available <= 0:
                continue
            items.append(MarketplaceItemOut(
                kind="EVENT",
                event=EventOut.model_validate(event),
                resource=ResourceOut.model_validate(resource),
                availability=availability,
            ))
    return items


@router.get("/listings", response_model=list[MarketplaceItemOut])
def listings(q: str | None = None, resource_type: str | None = None,
             limit: int = Query(default=50, le=200),
             db: Session = Depends(get_db), user=None):
    """Pre-event marketplace: transfer/resale offers (51)."""
    stmt = select(Listing).where(Listing.is_active.is_(True))
    listings = db.scalars(stmt.order_by(Listing.created_at.desc()).limit(limit)).all()
    items: list[MarketplaceItemOut] = []
    for listing in listings:
        right = listing.access_right
        event = right.resource.event
        if q and q.lower() not in event.title.lower():
            continue
        if resource_type and right.resource.type.value != resource_type:
            continue
        try:
            quote = PurchaseQuoteOut(**transfer_engine.quote_listing(db, listing))
        except transfer_engine.TransferError:
            continue
        items.append(MarketplaceItemOut(
            kind="LISTING",
            event=EventOut.model_validate(event),
            resource=ResourceOut.model_validate(right.resource),
            listing=ListingOut.model_validate(listing),
            quote=quote,
            availability=compute_resource_availability(db, right.resource),
        ))
    return items
