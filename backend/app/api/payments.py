"""Payments API — section 27. Wallet top-up, query + refund."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines import audit as audit_engine
from app.engines import payment as payment_engine
from app.models import AuditEventType, Payment, User, UserBalance
from app.schemas import BalanceOut, PaymentOut, TopUpCreate

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/balance", response_model=BalanceOut)
def my_balance(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    balance = payment_engine._balance(db, user.id)
    return {"available": balance.available, "escrow": balance.escrow}


@router.post("/topup", response_model=BalanceOut)
def topup(payload: TopUpCreate, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    """Demo top-up: the amount is credited to the wallet instantly.
    A real PSP (ЮKassa/Stripe) replaces this endpoint later — the ledger
    logic stays unchanged."""
    if payload.amount <= 0 or payload.amount > 1_000_000_00:
        raise HTTPException(400, detail={"code": "INVALID_AMOUNT",
                                         "message": "Amount must be between 1 and 10 000 ₽"})
    balance = payment_engine._balance(db, user.id)
    balance.available += payload.amount
    audit_engine.audit(db, AuditEventType.WALLET_TOPUP, "UserBalance", user.id,
                       actor_user_id=user.id, topup=payload.amount)
    db.commit()
    db.refresh(balance)
    return {"available": balance.available, "escrow": balance.escrow}


@router.get("/my", response_model=list[PaymentOut])
def my_payments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Payment).where(
        (Payment.payer_user_id == user.id) | (Payment.payee_user_id == user.id)
    ).order_by(Payment.created_at.desc())).all()


@router.get("/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "Payment not found")
    if payment.payer_user_id != user.id and payment.payee_user_id != user.id \
            and user.role.value != "ADMIN":
        raise HTTPException(403, "Not a payment participant")
    return payment


@router.post("/{payment_id}/refund", response_model=PaymentOut)
def refund(payment_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(404, "Payment not found")
    if user.role.value != "ADMIN" and payment.payer_user_id != user.id:
        raise HTTPException(403, "Only admin or payer can refund")
    try:
        payment_engine.refund(db, payment)
    except payment_engine.PaymentError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(payment)
    return payment
