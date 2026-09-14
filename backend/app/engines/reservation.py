"""Reservation Engine — sections 26, 61.

Reservation is a separate object with TTL; expiry is swept lazily on access
and confirmed only through the backend. Works for any resource type.
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import audit
from app.engines.notify import notify
from app.models import (
    AccessRight, AccessRightStatus, AuditEventType, Reservation, ReservationStatus, Resource,
    utcnow,
)
from app.core.config import settings


class ReservationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def sweep_expired(db: Session) -> int:
    """Expire reservations whose TTL passed; free held capacity."""
    now = utcnow()
    stale = db.scalars(
        select(Reservation).where(
            Reservation.status.in_([ReservationStatus.CREATED, ReservationStatus.HELD]),
            Reservation.expires_at < now,
        )
    ).all()
    for reservation in stale:
        reservation.status = ReservationStatus.EXPIRED
        resource = db.get(Resource, reservation.resource_id)
        if reservation.access_right_id:
            right = db.get(AccessRight, reservation.access_right_id)
            if right and right.status == AccessRightStatus.RESERVED:
                right.status = AccessRightStatus.CANCELLED
        audit(db, AuditEventType.RESERVATION_EXPIRED, "Reservation", reservation.id)
        if resource:
            from app.engines import waitlist as waitlist_engine
            waitlist_engine.on_capacity_freed(db, resource)
    if stale:
        db.flush()
    return len(stale)


def create_reservation(
    db: Session, user_id: int, resource: Resource, amount: int = 0
) -> Reservation:
    sweep_expired(db)
    from app.engines.availability import compute_resource_availability
    availability = compute_resource_availability(db, resource)
    if availability.available <= 0:
        raise ReservationError("NO_AVAILABILITY", "No availability for this resource", 409)

    reservation = Reservation(
        resource_id=resource.id,
        user_id=user_id,
        status=ReservationStatus.HELD,
        amount=amount or resource.price_base,
        expires_at=utcnow() + timedelta(seconds=settings.RESERVATION_TTL_SECONDS),
        created_at=utcnow(),
    )
    db.add(reservation)
    db.flush()
    audit(db, AuditEventType.RESERVATION_CREATED, "Reservation", reservation.id,
          actor_user_id=user_id, resource_id=resource.id,
          expires_at=reservation.expires_at.isoformat())
    notify(db, user_id, "RESERVATION_CREATED", "Reservation held",
           "Confirm before the timer runs out", reservation_id=reservation.id)
    return reservation


def confirm_reservation(db: Session, user_id: int, reservation_id: int) -> Reservation:
    reservation = db.get(Reservation, reservation_id)
    if not reservation or reservation.user_id != user_id:
        raise ReservationError("NOT_FOUND", "Reservation not found", 404)
    sweep_expired(db)
    if reservation.status == ReservationStatus.CONFIRMED:
        return reservation  # idempotent
    if reservation.status != ReservationStatus.HELD:
        raise ReservationError("INVALID_STATE",
                               f"Reservation is {reservation.status.value}", 409)
    # a paid reservation cannot be confirmed without a captured payment —
    # otherwise an AccessRight would be issued with money never taken
    if reservation.amount > 0 and reservation.payment_status != "CAPTURED":
        raise ReservationError("PAYMENT_REQUIRED",
                               "Reservation must be paid before confirmation", 409)

    import secrets as _secrets
    from app.core.security import generate_token_code
    from app.models import AccessRightKind
    resource = db.get(Resource, reservation.resource_id)
    if resource is None:
        raise ReservationError("RESOURCE_NOT_FOUND", "Resource not found", 404)
    kind = {
        "TICKET": AccessRightKind.TICKET,
        "TIME_SLOT": AccessRightKind.SLOT,
        "WAITLIST": AccessRightKind.WAITLIST_PRIORITY,
        "EVENT_REGISTRATION": AccessRightKind.REGISTRATION,
    }.get(resource.type.value, AccessRightKind.ACCESS_PASS)

    right = AccessRight(
        token_code=generate_token_code("AT"),
        kind=kind,
        resource_id=resource.id,
        event_id=resource.event_id,
        owner_user_id=user_id,
        status=AccessRightStatus.OWNED,
        transferable=resource.is_transferable,
        resellable=resource.is_resellable,
        payload=dict(resource.payload or {}),
        one_time_secret=_secrets.token_hex(16),
        created_at=utcnow(),
    )
    db.add(right)
    db.flush()

    reservation.status = ReservationStatus.CONFIRMED
    reservation.access_right_id = right.id
    reservation.confirmed_at = utcnow()
    if reservation.payment_status != "CAPTURED" and reservation.amount == 0:
        reservation.payment_status = "NOT_REQUIRED"
    audit(db, AuditEventType.RESERVATION_CONFIRMED, "Reservation", reservation.id,
          actor_user_id=user_id, access_right_id=right.id)
    audit(db, AuditEventType.POSITION_ASSIGNED, "AccessRight", right.id,
          actor_user_id=user_id, resource_id=resource.id)
    return reservation


def cancel_reservation(db: Session, user_id: int, reservation_id: int) -> Reservation:
    reservation = db.get(Reservation, reservation_id)
    if not reservation or reservation.user_id != user_id:
        raise ReservationError("NOT_FOUND", "Reservation not found", 404)
    if reservation.status in (ReservationStatus.CONFIRMED, ReservationStatus.HELD,
                              ReservationStatus.CREATED):
        reservation.status = ReservationStatus.CANCELLED
        if reservation.access_right_id:
            right = db.get(AccessRight, reservation.access_right_id)
            if right and right.status not in (AccessRightStatus.USED,):
                right.status = AccessRightStatus.CANCELLED
        audit(db, AuditEventType.ACCESS_RIGHT_CANCELLED, "Reservation", reservation.id,
              actor_user_id=user_id)
        from app.engines import waitlist as waitlist_engine
        resource = db.get(Resource, reservation.resource_id)
        if resource is not None:
            waitlist_engine.on_capacity_freed(db, resource)
    return reservation
