"""Analytics API — section 59."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models import (
    AuditEvent, CheckIn, Dispute, Event, Payment, PaymentStatus, Queue, Reservation, Transfer,
    TransferKind, User,
)
from app.schemas import AnalyticsOut, AuditEventOut

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsOut)
def overview(db: Session = Depends(get_db), user=Depends(require_admin)):
    count = lambda q: db.scalar(q) or 0  # noqa: E731
    events = count(select(func.count(Event.id)))
    queues = count(select(func.count(Queue.id)))
    registrations = count(select(func.count(Reservation.id)))
    transfers = count(select(func.count(Transfer.id)).where(Transfer.kind == TransferKind.TRANSFER))
    resales = count(select(func.count(Transfer.id)).where(Transfer.kind == TransferKind.RESALE))
    checkins = count(select(func.count(CheckIn.id)).where(CheckIn.result == "VALID"))
    disputes = count(select(func.count(Dispute.id)))
    fraud_flags = count(select(func.count(AuditEvent.id)).where(
        AuditEvent.type == "FraudFlagged"))
    revenue = count(select(func.coalesce(func.sum(Payment.fee_amount), 0)).where(
        Payment.status == PaymentStatus.CAPTURED))
    cancellations = count(select(func.count(Reservation.id)).where(
        Reservation.status == "CANCELLED"))
    conversion = (checkins / registrations * 100.0) if registrations else 0.0
    return AnalyticsOut(
        events=events, queues=queues, registrations=registrations, transfers=transfers,
        resales=resales, checkins=checkins, disputes=disputes, fraud_flags=fraud_flags,
        revenue=revenue, conversion=round(conversion, 2), cancellations=cancellations,
    )


@router.get("/audit", response_model=list[AuditEventOut])
def audit_log(limit: int = 200, db: Session = Depends(get_db), user=Depends(require_admin)):
    return db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc())
                      .limit(limit)).all()
