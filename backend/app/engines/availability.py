"""Availability Engine — sections 52, 83.

All availability values are computed server-side; the client never derives them.
Works uniformly for every resource type (Resource Adapter Architecture, 39).
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AccessRight, AccessRightStatus, CheckIn, Event, Listing, QueueMembership, Reservation,
    ReservationStatus, Resource, WaitlistEntry,
)
from app.schemas import AvailabilityOut, EventInventoryOut


def compute_resource_availability(db: Session, resource: Resource) -> AvailabilityOut:
    ar = aliased_counts(db, resource.id)
    in_waitlist = db.scalar(
        select(func.count(WaitlistEntry.id)).where(
            WaitlistEntry.waitlist.has(resource_id=resource.id),
            WaitlistEntry.status.in_(["WAITING", "OFFERED"]),
        )
    ) or 0
    in_queue = db.scalar(
        select(func.count(QueueMembership.id)).where(
            QueueMembership.queue.has(resource_id=resource.id),
            QueueMembership.active.is_(True),
        )
    ) or 0
    # held (unconfirmed) reservations also consume capacity — otherwise
    # two concurrent holds oversell the resource (section 26)
    held = db.scalar(
        select(func.count(Reservation.id)).where(
            Reservation.resource_id == resource.id,
            Reservation.status.in_([ReservationStatus.CREATED, ReservationStatus.HELD]),
        )
    ) or 0
    return AvailabilityOut(
        resource_id=resource.id,
        total_capacity=resource.capacity,
        confirmed=ar["confirmed"] + held,
        available=max(resource.capacity - ar["confirmed"] - held, 0),
        in_queue=in_queue,
        in_waitlist=in_waitlist,
        listed=ar["listed"],
        sold=ar["sold"],
        checked_in=ar["checked_in"],
    )


def aliased_counts(db: Session, resource_id: int) -> dict:
    def count(statuses: list[str]) -> int:
        return db.scalar(
            select(func.count(AccessRight.id)).where(
                AccessRight.resource_id == resource_id,
                AccessRight.status.in_(statuses),
            )
        ) or 0

    checked_in = db.scalar(
        select(func.count(CheckIn.id)).where(
            CheckIn.access_right.has(resource_id=resource_id),
            CheckIn.result == "VALID",
        )
    ) or 0
    return {
        "confirmed": count(["OWNED", "LISTED", "TRANSFER_PENDING", "USED"]),
        "listed": count(["LISTED"]),
        "sold": count(["USED"]),
        "checked_in": checked_in,
    }


def compute_event_inventory(db: Session, event: Event) -> EventInventoryOut:
    resources = db.scalars(select(Resource).where(Resource.event_id == event.id)).all()
    total = confirmed = listed = sold = checked_in = in_queue = in_waitlist = 0
    for resource in resources:
        av = compute_resource_availability(db, resource)
        total += av.total_capacity
        confirmed += av.confirmed
        listed += av.listed
        sold += av.sold
        checked_in += av.checked_in
        in_queue += av.in_queue
        in_waitlist += av.in_waitlist
    if event.capacity is not None:
        total = event.capacity
    return EventInventoryOut(
        event_id=event.id,
        total_capacity=total,
        confirmed=confirmed,
        available=max(total - confirmed, 0),
        in_queue=in_queue,
        in_waitlist=in_waitlist,
        transferable_listed=listed,
        sold=sold,
        checked_in=checked_in,
    )
