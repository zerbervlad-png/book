"""Disputes API — section 28."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines import payment as payment_engine
from app.models import (
    AccessRight, AccessRightStatus, Dispute, DisputeStatus, Payment, Transfer,
    TransferStatus, User, utcnow,
)
from app.schemas import DisputeCreate, DisputeOut

router = APIRouter(prefix="/disputes", tags=["disputes"])


@router.post("", response_model=DisputeOut, status_code=201)
def open_dispute(payload: DisputeCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    if payload.transfer_id is None and payload.access_right_id is None:
        raise HTTPException(400, "transfer_id or access_right_id required")
    # only a participant of the transfer may open a dispute — otherwise any
    # user could spam disputes on deals they are not part of
    if payload.transfer_id is not None:
        transfer = db.get(Transfer, payload.transfer_id)
        if not transfer:
            raise HTTPException(404, "Transfer not found")
        if user.id not in (transfer.from_user_id, transfer.to_user_id) \
                and user.role.value != "ADMIN":
            raise HTTPException(403, "Not a participant of this transfer")
    elif payload.access_right_id is not None:
        right = db.get(AccessRight, payload.access_right_id)
        if not right:
            raise HTTPException(404, "Access right not found")
        if right.owner_user_id != user.id and user.role.value != "ADMIN":
            raise HTTPException(403, "Not the owner of this access right")
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
        transfer = db.get(Transfer, dispute.transfer_id)
        if transfer and transfer.status != TransferStatus.COMPLETED:
            # cancel the transfer itself so the buyer cannot pay later for a
            # right that is being revoked (and a zombie deal doesn't linger)
            from app.engines import transfer as transfer_engine
            try:
                transfer_engine.cancel_transfer(db, transfer.from_user_id, transfer.id)
            except transfer_engine.TransferError:
                pass  # already cancelled/completed — nothing to do
        payment = db.scalar(select(Payment).where(
            Payment.transfer_id == dispute.transfer_id,
            Payment.status == payment_engine.PaymentStatus.CAPTURED))
        if payment:
            try:
                payment_engine.refund(db, payment)
            except payment_engine.PaymentError as e:
                raise HTTPException(e.status_code, detail={
                    "code": e.code, "message": f"Refund not possible: {e.message}"})
        # the buyer must not keep the access right they were refunded for —
        # revoke it, otherwise refund resolutions double-spend (money + goods)
        transfer = db.get(Transfer, dispute.transfer_id)
        if transfer and transfer.access_right:
            right = transfer.access_right
            if right.status not in (AccessRightStatus.USED, AccessRightStatus.CANCELLED):
                right.status = AccessRightStatus.CANCELLED
        dispute.status = DisputeStatus.RESOLVED_REFUNDED
    elif action == "reject":
        dispute.status = DisputeStatus.RESOLVED_REJECTED
    elif action == "close":
        dispute.status = DisputeStatus.CLOSED
    else:
        raise HTTPException(400, "action must be refund | reject | close")
    dispute.resolution_notes = notes
    dispute.resolved_at = utcnow()
    db.commit()
    db.refresh(dispute)
    return dispute
