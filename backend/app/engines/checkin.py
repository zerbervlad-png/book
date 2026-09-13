"""Check-in Engine — sections 11, 29, 30, 49, 65.

Universal across QR / barcode / token / code / manual / API. Single-use
enforcement: a used token can never pass twice. GPS is accepted only as an
auxiliary factor and never proves queue membership.
"""
import hashlib
import hmac

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import audit
from app.models import (
    AccessRight, AccessRightStatus, AuditEventType, CheckIn, CheckInMethod, CheckInResult,
    EventStatus, utcnow,
)


class CheckInError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def _find_right(db: Session, presented: str) -> AccessRight | None:
    presented = presented.strip()
    right = db.scalar(select(AccessRight).where(AccessRight.token_code == presented))
    if right:
        return right
    # one-time code derived from the secret: OTP-like hex code
    for candidate in db.scalars(
        select(AccessRight).where(AccessRight.one_time_secret != "")
    ):
        code = _one_time_code(candidate.one_time_secret)
        if hmac.compare_digest(code, presented):
            return candidate
    return None


def _one_time_code(secret: str) -> str:
    return hashlib.sha256(f"otp:{secret}".encode()).hexdigest()[:8].upper()


def check_in(db: Session, presented: str, method: CheckInMethod,
             checked_by_user_id: int | None = None,
             gps: dict | None = None) -> tuple[CheckInResult, CheckIn | None, AccessRight | None]:
    """Returns (result, record, right). Never raises for invalid tokens —
    returns a result code, as required by section 29."""
    right = _find_right(db, presented)
    if right is None:
        record = _record(db, None, None, None, method, CheckInResult.INVALID, presented,
                         checked_by_user_id, gps)
        audit(db, AuditEventType.CHECKIN_REJECTED, "CheckIn", record.id,
              actor_user_id=checked_by_user_id, reason="unknown_token")
        return CheckInResult.INVALID, record, None

    event = right.resource.event
    if event.status == EventStatus.CANCELLED:
        return _finish(db, right, method, CheckInResult.CANCELLED, presented,
                       checked_by_user_id, gps)
    if right.status == AccessRightStatus.USED:
        return _finish(db, right, method, CheckInResult.USED, presented,
                       checked_by_user_id, gps)
    if right.status == AccessRightStatus.TRANSFERRED:
        return _finish(db, right, method, CheckInResult.TRANSFERRED, presented,
                       checked_by_user_id, gps)
    if right.status in (AccessRightStatus.CANCELLED,):
        return _finish(db, right, method, CheckInResult.CANCELLED, presented,
                       checked_by_user_id, gps)
    if right.expires_at is not None and right.expires_at < utcnow():
        return _finish(db, right, method, CheckInResult.EXPIRED, presented,
                       checked_by_user_id, gps)
    if right.status in (AccessRightStatus.TRANSFER_PENDING, AccessRightStatus.LISTED):
        return _finish(db, right, method, CheckInResult.INVALID, presented,
                       checked_by_user_id, gps)

    # VALID — mark used exactly once
    right.status = AccessRightStatus.USED
    right.used_at = utcnow()
    result = _finish(db, right, method, CheckInResult.VALID, presented,
                     checked_by_user_id, gps)
    return CheckInResult.VALID, result[1], right


def _finish(db, right, method, result, presented, checked_by_user_id, gps):
    record = _record(db, right.id, right.event_id, right.owner_user_id, method, result,
                     presented, checked_by_user_id, gps)
    audit(db, AuditEventType.CHECKIN_COMPLETED, "CheckIn", record.id,
          actor_user_id=checked_by_user_id, result=result.value,
          access_right_id=right.id, gps_auxiliary=bool(gps))
    return result, record, right


def _record(db, access_right_id, event_id, user_id, method, result, presented,
            checked_by_user_id, gps) -> CheckIn:
    record = CheckIn(
        access_right_id=access_right_id,
        event_id=event_id,
        user_id=user_id,
        method=method,
        result=result,
        presented=presented[:128],
        checked_by_user_id=checked_by_user_id,
        gps=gps or {},  # auxiliary signal only (sections 10, 49)
        checked_at=utcnow(),
    )
    db.add(record)
    db.flush()
    return record
