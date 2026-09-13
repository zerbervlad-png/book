"""Fraud / Anti-abuse Engine — sections 31, 60.

Detects: mass account creation, rapid position creation, suspicious transfers,
frequent cancellations, transfers between linked accounts, token reuse,
attempts to sell already-used rights. Raises risk scores; never decides on
GPS alone (10, 49, 65).
"""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.audit import audit
from app.models import (
    AccessRight, AccessRightStatus, AuditEventType, CheckIn, QueueMembership, Reservation,
    Transfer, User, UserTelemetry, utcnow,
)

RISK_THRESHOLD = 100.0


class FraudError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def _add_risk(db: Session, user_id: int, points: float, reason: str) -> float:
    user = db.get(User, user_id)
    if user is None:
        return 0.0
    user.risk_score += points
    audit(db, AuditEventType.FRAUD_FLAGGED, "User", user_id,
          actor_user_id=user_id, reason=reason, points=points,
          risk_score=user.risk_score)
    if user.risk_score > RISK_THRESHOLD:
        user.is_active = False
    return user.risk_score


def check_registration_burst(db: Session, email_domain: str) -> None:
    """Mass creation of accounts from one domain in a short window."""
    window_start = utcnow() - timedelta(hours=1)
    count = db.scalar(
        select(func.count(User.id)).where(
            User.email.like(f"%@{email_domain}"),
            User.created_at >= window_start,
        )
    ) or 0
    if count > 20:
        raise FraudError("REGISTRATION_BURST",
                         "Too many accounts created recently", 429)


def check_rapid_joining(db: Session, user_id: int) -> None:
    """Rapid creation of many positions (31)."""
    window_start = utcnow() - timedelta(minutes=10)
    joined = db.scalar(
        select(func.count(QueueMembership.id)).where(
            QueueMembership.user_id == user_id,
            QueueMembership.joined_at >= window_start,
        )
    ) or 0
    if joined > 15:
        _add_risk(db, user_id, 20.0 * joined, "rapid_position_creation")
        raise FraudError("TOO_MANY_JOINS", "Suspicious joining activity", 429)


def check_frequent_cancellations(db: Session, user_id: int) -> None:
    window_start = utcnow() - timedelta(hours=24)
    cancelled = db.scalar(
        select(func.count(Reservation.id)).where(
            Reservation.user_id == user_id,
            Reservation.status == "CANCELLED",
            Reservation.created_at >= window_start,
        )
    ) or 0
    if cancelled > 10:
        _add_risk(db, user_id, 10.0 * cancelled, "frequent_cancellations")


def check_transfer_patterns(db: Session, from_user_id: int, to_user_id: int) -> None:
    """Transfers between linked accounts (31): same-domain emails, high frequency."""
    from_user = db.get(User, from_user_id)
    to_user = db.get(User, to_user_id)
    if from_user and to_user:
        from_domain = from_user.email.split("@")[-1]
        to_domain = to_user.email.split("@")[-1]
        if from_domain == to_domain:
            _add_risk(db, from_user_id, 15.0, "linked_account_transfer")
            _add_risk(db, to_user_id, 15.0, "linked_account_transfer")
    window_start = utcnow() - timedelta(hours=1)
    recent = db.scalar(
        select(func.count(Transfer.id)).where(
            Transfer.from_user_id == from_user_id,
            Transfer.created_at >= window_start,
        )
    ) or 0
    if recent > 10:
        _add_risk(db, from_user_id, 25.0, "transfer_frequency")


def check_user_active(db: Session, user: User) -> None:
    if not user.is_active:
        raise FraudError("USER_BLOCKED", "Account is blocked due to risk policy", 403)


def record_gps_telemetry(db: Session, user_id: int, lat: float | None, lng: float | None,
                          accuracy_m: float | None, event_id: int | None = None) -> UserTelemetry:
    """GPS is stored as auxiliary signal only (10, 49). Implausible accuracy or
    teleport-speed movement flags the telemetry, but never blocks or removes
    the user from a queue by itself."""
    is_spoof_suspect = False
    if lat is not None and lng is not None:
        if accuracy_m is not None and accuracy_m < 1.0:
            is_spoof_suspect = True  # unrealistically perfect accuracy
        last = db.scalar(
            select(UserTelemetry).where(UserTelemetry.user_id == user_id)
            .order_by(UserTelemetry.recorded_at.desc()).limit(1)
        )
        if last and last.lat is not None:
            dt = (utcnow() - last.recorded_at).total_seconds()
            dist_m = ((lat - last.lat) ** 2 + (lng - last.lng) ** 2) ** 0.5 * 111_000
            if dt > 0 and dist_m / dt > 900:  # >900 m/s
                is_spoof_suspect = True
    telemetry = UserTelemetry(
        user_id=user_id, event_id=event_id, lat=lat, lng=lng,
        accuracy_m=accuracy_m, is_spoof_suspect=is_spoof_suspect,
        recorded_at=utcnow(),
    )
    db.add(telemetry)
    if is_spoof_suspect:
        _add_risk(db, user_id, 5.0, "gps_spoof_suspect")
    db.flush()
    return telemetry


def guard_listing_of_used_right(db: Session, right: AccessRight) -> None:
    """Attempt to sell an already used right (31)."""
    if right.status == AccessRightStatus.USED:
        raise FraudError("RIGHT_ALREADY_USED", "This right was already used", 409)


def count_token_reuse_attempts(db: Session, token_code: str) -> int:
    return db.scalar(
        select(func.count(CheckIn.id)).where(
            CheckIn.presented == token_code,
            CheckIn.result.in_(["USED", "INVALID", "TRANSFERRED", "CANCELLED"]),
        )
    ) or 0
