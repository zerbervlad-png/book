"""Disputes API — section 28."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines import payment as payment_engine
from app.models import Dispute, DisputeStatus, Payment, Transfer, User
from app.schemas import DisputeCreate, DisputeOut

router = APIRouter(prefix="/disputes", tags=["disputes"])


@router.post("", response_model=DisputeOut, status_code=201)
def open_dispute(payload: DisputeCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    if payload.transfer_id is None and payload.access_right_id is None:
        raise HTTPException(400, "transfer_id or access_right_id required")
    dispute = Dispute(
        transfer_id=payload.transfer_id,
        access_right_id=payload.access_right_id,
        opened_by_user_id=user.id,
        reason=payload.reason,
        description=payload.description,
        status=DisputeStatus.OPEN,
    )
    db.add(dispute)
    db.commit()
    db.refresh(dispute)
    return dispute


@router.get("/my", response_model=list[DisputeOut])
def my_disputes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Dispute).where(
        Dispute.opened_by_user_id == user.id).order_by(Dispute.created_at.desc())).all()


@router.post("/{dispute_id}/resolve", response_model=DisputeOut)
def resolve(dispute_id: int, action: str, notes: str = "",
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role.value != "ADMIN":
        raise HTTPException(403, "Admin only")
    dispute = db.get(Dispute, dispute_id)
    if not dispute:
        raise HTTPException(404, "Dispute not found")
    if dispute.status not in (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW):
        raise HTTPException(409, "Dispute already resolved")

    if action == "refund" and dispute.transfer_id:
        payment = db.scalar(select(Payment).where(Payment.transfer_id == dispute.transfer_id))
        if payment:
            try:
                payment_engine.refund(db, payment)
            except payment_engine.PaymentError as e:
                raise HTTPException(e.status_code, detail={
                    "code": e.code, "message": f"Refund not possible: {e.message}"})
        dispute.status = DisputeStatus.RESOLVED_REFUNDED
    elif action == "reject":
        dispute.status = DisputeStatus.RESOLVED_REJECTED
    elif action == "close":
        dispute.status = DisputeStatus.CLOSED
    else:
        raise HTTPException(400, "action must be refund | reject | close")
    dispute.resolution_notes = notes
    dispute.resolved_at = __import__("app.models", fromlist=["utcnow"]).utcnow()
    db.commit()
    db.refresh(dispute)
    return dispute
