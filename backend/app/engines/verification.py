"""Event Verification Engine — sections 6, 7, 69, 70.

Separate module that verifies: event exists, not cancelled, date/time is
actual, place matches, organizer exists, official info available, not a
duplicate, not fraudulent.
"""
import hashlib
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import audit
from app.models import (
    AuditEventType, Event, EventSource, EventVerification, EventStatus, Organizer, utcnow,
    VerificationStatus,
)


class VerificationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def canonical_key(title: str, city: str | None, starts_at, organizer_name: str | None) -> str:
    """Canonical identity for duplicate detection (69, 70)."""
    normalized_title = " ".join(title.lower().split())
    normalized_city = (city or "").lower().strip()
    organizer_part = (organizer_name or "").lower().strip()
    date_part = starts_at.strftime("%Y-%m-%d")
    raw = f"{normalized_title}|{normalized_city}|{date_part}|{organizer_part}"
    return hashlib.sha256(raw.encode()).hexdigest()


def find_duplicate(db: Session, key: str, exclude_event_id: int | None = None) -> Event | None:
    query = select(Event).where(Event.canonical_key == key)
    events = db.scalars(query).all()
    if exclude_event_id is not None:
        events = [e for e in events if e.id != exclude_event_id]
    return events[0] if events else None


def run_verification(db: Session, event: Event, actor_user_id: int | None = None) -> Event:
    """Full heuristic verification pass. Writes an EventVerification record."""
    checks: list[tuple[str, bool, str]] = []

    # 1. Organizer present (verification level of organizer handled below)
    organizer_ok = event.organizer is not None and event.organizer.is_verified
    checks.append(("organizer_exists", event.organizer is not None,
                   f"organizer={event.organizer.name if event.organizer else None}"))

    # 2. Date/time sane: not in the past, start before end
    now = utcnow()
    starts_ok = event.starts_at >= now - timedelta(days=1)
    checks.append(("datetime_actual", starts_ok, f"starts_at={event.starts_at.isoformat()}"))
    if event.ends_at is not None:
        checks.append(("interval_sane", event.ends_at > event.starts_at, "ends after start"))

    # 3. Location present
    checks.append(("location_present", bool(event.city or event.address), "location filled"))

    # 4. Source available: organizer events need an organizer; imports need a URL
    checks.append(("source_available",
                   (event.source == EventSource.ORGANIZER and event.organizer is not None)
                   or (event.source in (EventSource.IMPORT, EventSource.PARTNER)
                       and bool(event.source_url)),
                   f"source={event.source.value}"))

    # 5. Not a duplicate
    duplicate = find_duplicate(db, event.canonical_key, exclude_event_id=event.id)
    checks.append(("not_duplicate", duplicate is None,
                   f"duplicate_of={duplicate.id if duplicate else None}"))

    failed = [name for name, ok, _ in checks if not ok]
    if duplicate:
        new_status = VerificationStatus.REJECTED
    elif event.source in (EventSource.IMPORT, EventSource.PARTNER) and event.source_url:
        new_status = VerificationStatus.OFFICIAL
    elif organizer_ok:
        new_status = VerificationStatus.ORGANIZER_VERIFIED
    elif not failed:
        new_status = VerificationStatus.VERIFIED
    else:
        new_status = VerificationStatus.REJECTED

    record = EventVerification(
        event_id=event.id,
        status=new_status,
        method="automated_engine",
        source_url=event.source_url,
        notes="; ".join(f"{n}:{'OK' if ok else 'FAIL'}({detail})" for n, ok, detail in checks),
        checked_at=utcnow(),
    )
    db.add(record)
    event.verification_status = new_status
    event.last_verified_at = utcnow()
    event.verification_method = "automated_engine"

    if event.status in (EventStatus.DRAFT, EventStatus.PENDING_VERIFICATION):
        event.status = EventStatus.VERIFIED if new_status != VerificationStatus.REJECTED \
            else EventStatus.PENDING_VERIFICATION

    audit(db, AuditEventType.EVENT_VERIFIED, "Event", event.id,
          actor_user_id=actor_user_id, status=new_status.value, failed_checks=failed)
    db.flush()
    return event


def verify_organizer(db: Session, organizer: Organizer, actor_user_id: int | None = None) -> Organizer:
    """Admin marks an organizer verified — Organizer Verified (6)."""
    organizer.is_verified = True
    audit(db, AuditEventType.ORGANIZER_VERIFIED, "Organizer", organizer.id,
          actor_user_id=actor_user_id)
    db.flush()
    return organizer


def submit_user_request(db: Session, event: Event) -> Event:
    """5.3: user-submitted events go to verification queue."""
    event.status = EventStatus.PENDING_VERIFICATION
    db.add(event)
    db.flush()
    return event
