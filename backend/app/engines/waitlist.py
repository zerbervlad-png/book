"""Waitlist Engine — sections 17, 3.4.

When capacity frees up the engine: determines the next user, creates a
reservation window, notifies and gives limited time to confirm; otherwise
the place moves to the next user.
"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.engines.audit import audit
from app.engines.notify import notify
from app.models import (
    AccessRight, AccessRightKind, AccessRightStatus, AuditEventType, Reservation,
    ReservationStatus, Resource, Waitlist, WaitlistEntry, WaitlistEntryStatus, utcnow,
)
from app.core.security import generate_token_code


class WaitlistError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def ensure_waitlist(db: Session, resource: Resource) -> Waitlist:
    waitlist = db.scalar(select(Waitlist).where(Waitlist.resource_id == resource.id))
    if waitlist is None:
        waitlist = Waitlist(resource_id=resource.id)
        db.add(waitlist)
        db.flush()
    return waitlist


def join(db: Session, user_id: int, resource: Resource) -> WaitlistEntry:
    waitlist = ensure_waitlist(db, resource)
    existing = db.scalar(select(WaitlistEntry).where(
        WaitlistEntry.waitlist_id == waitlist.id,
        WaitlistEntry.user_id == user_id,
        WaitlistEntry.status.in_([WaitlistEntryStatus.WAITING, WaitlistEntryStatus.OFFERED]),
    ))
    if existing:
        raise WaitlistError("ALREADY_IN_WAITLIST", "Already in this waitlist", 409)

    max_pos = db.scalar(
        select(func.max(WaitlistEntry.position)).where(WaitlistEntry.waitlist_id == waitlist.id)
    )
    entry = WaitlistEntry(
        waitlist_id=waitlist.id,
        user_id=user_id,
        position=(max_pos or 0) + 1,
        status=WaitlistEntryStatus.WAITING,
        created_at=utcnow(),
    )
    db.add(entry)
    db.flush()
    notify(db, user_id, "WAITLIST_JOINED", f"You are #{entry.position} in the waitlist",
           waitlist_entry_id=entry.id)
    return entry


def leave(db: Session, user_id: int, resource: Resource) -> None:
    waitlist = ensure_waitlist(db, resource)
    entry = db.scalar(select(WaitlistEntry).where(
        WaitlistEntry.waitlist_id == waitlist.id,
        WaitlistEntry.user_id == user_id,
        WaitlistEntry.status.in_([WaitlistEntryStatus.WAITING, WaitlistEntryStatus.OFFERED]),
    ))
    if not entry:
        raise WaitlistError("NOT_IN_WAITLIST", "Not in this waitlist", 404)
    entry.status = WaitlistEntryStatus.CANCELLED
    db.flush()


def sweep_expired_offers(db: Session) -> int:
    """Pass expired offers to the next user in line."""
    now = utcnow()
    expired = db.scalars(select(WaitlistEntry).where(
        WaitlistEntry.status == WaitlistEntryStatus.OFFERED,
        WaitlistEntry.offer_expires_at < now,
    )).all()
    for entry in expired:
        entry.status = WaitlistEntryStatus.PASSED
        _offer_next(db, entry.waitlist)
    if expired:
        db.flush()
    return len(expired)


def _offer_next(db: Session, waitlist: Waitlist) -> WaitlistEntry | None:
    next_entry = db.scalar(select(WaitlistEntry).where(
        WaitlistEntry.waitlist_id == waitlist.id,
        WaitlistEntry.status == WaitlistEntryStatus.WAITING,
    ).order_by(WaitlistEntry.position))
    if next_entry is None:
        return None
    return offer_entry(db, next_entry)


def offer_entry(db: Session, entry: WaitlistEntry) -> WaitlistEntry:
    entry.status = WaitlistEntryStatus.OFFERED
    entry.offered_at = utcnow()
    entry.offer_expires_at = utcnow() + timedelta(seconds=settings.WAITLIST_OFFER_TTL_SECONDS)
    notify(db, entry.user_id, "WAITLIST_OFFERED", "A place became available!",
           "Confirm your reservation before the offer expires",
           waitlist_entry_id=entry.id, expires_at=entry.offer_expires_at.isoformat())
    db.flush()
    return entry


def on_capacity_freed(db: Session, resource: Resource) -> WaitlistEntry | None:
    """Called when a place frees up (cancellation, expiry, transfer-out)."""
    waitlist = db.scalar(select(Waitlist).where(Waitlist.resource_id == resource.id))
    if waitlist is None or not waitlist.is_open:
        return None
    return _offer_next(db, waitlist)


def confirm_offer(db: Session, user_id: int, entry_id: int) -> Reservation:
    """17: user confirms within the reservation window -> gets a reservation."""
    sweep_expired_offers(db)
    entry = db.get(WaitlistEntry, entry_id)
    if not entry or entry.user_id != user_id:
        raise WaitlistError("NOT_FOUND", "Waitlist entry not found", 404)
    if entry.status != WaitlistEntryStatus.OFFERED:
        raise WaitlistError("INVALID_STATE",
                            f"Entry is {entry.status.value}", 409)
    resource = entry.waitlist.resource

    # the freed place may have been taken by a direct reservation while the
    # offer was open — verify availability before issuing a new one
    from app.engines.availability import compute_resource_availability
    availability = compute_resource_availability(db, resource)
    if availability.available <= 0:
        entry.status = WaitlistEntryStatus.PASSED
        db.flush()
        raise WaitlistError("NO_AVAILABILITY",
                            "The place was taken while your offer was open", 409)

    reservation = Reservation(
        resource_id=resource.id,
        user_id=user_id,
        status=ReservationStatus.HELD,
        amount=resource.price_base,
        expires_at=utcnow() + timedelta(seconds=settings.RESERVATION_TTL_SECONDS),
        created_at=utcnow(),
        payload={"waitlist_entry_id": entry.id},
    )
    db.add(reservation)
    entry.status = WaitlistEntryStatus.CONFIRMED
    db.flush()
    audit(db, AuditEventType.RESERVATION_CREATED, "Reservation", reservation.id,
          actor_user_id=user_id, resource_id=resource.id, via="waitlist")
    return reservation


def issue_waitlist_priority_right(db: Session, reservation: Reservation) -> AccessRight:
    """When a waitlist reservation is confirmed, user gets a WAITLIST_PRIORITY right."""
    import secrets as _secrets
    resource = db.get(Resource, reservation.resource_id)
    right = AccessRight(
        token_code=generate_token_code("AT"),
        kind=AccessRightKind.WAITLIST_PRIORITY,
        resource_id=resource.id,
        event_id=resource.event_id,
        owner_user_id=reservation.user_id,
        position=None,
        status=AccessRightStatus.OWNED,
        transferable=resource.is_transferable,
        resellable=resource.is_resellable,
        payload={"waitlist": True},
        one_time_secret=_secrets.token_hex(16),
        created_at=utcnow(),
    )
    db.add(right)
    reservation.access_right_id = right.id
    reservation.status = ReservationStatus.CONFIRMED
    reservation.confirmed_at = utcnow()
    db.flush()
    audit(db, AuditEventType.POSITION_ASSIGNED, "AccessRight", right.id,
          actor_user_id=reservation.user_id, resource_id=resource.id, kind="WAITLIST_PRIORITY")
    return right
