"""Reservations API — section 26 (payments for reservations — section 27)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines import payment as payment_engine
from app.engines import reservation as reservation_engine
from app.models import Resource, User
from app.schemas import PaymentCreate, PaymentOut, ReservationCreate, ReservationOut

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.post("", response_model=ReservationOut, status_code=201)
def create_reservation(payload: ReservationCreate, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    resource = db.get(Resource, payload.resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    if resource.event.status.value in ("CANCELLED", "COMPLETED"):
        raise HTTPException(409, detail={"code": "EVENT_NOT_ACTIVE",
                                         "message": "Event is cancelled or completed"})
    try:
        reservation = reservation_engine.create_reservation(
            db, user.id, resource, amount=payload.amount or resource.price_base)
    except reservation_engine.ReservationError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(reservation)
    return reservation


@router.get("/my", response_model=list[ReservationOut])
def my_reservations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    reservation_engine.sweep_expired(db)
    # sweeping expires reservations and frees capacity — persist it
    db.commit()
    from app.models import Reservation
    return db.scalars(select(Reservation).where(
        Reservation.user_id == user.id).order_by(Reservation.created_at.desc())).all()


@router.get("/{reservation_id}", response_model=ReservationOut)
def get_reservation(reservation_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    from app.models import Reservation
    reservation = db.get(Reservation, reservation_id)
    if not reservation or reservation.user_id != user.id:
        raise HTTPException(404, "Reservation not found")
    reservation_engine.sweep_expired(db)
    db.refresh(reservation)
    return reservation


@router.post("/{reservation_id}/confirm", response_model=ReservationOut)
def confirm(reservation_id: int, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    try:
        reservation = reservation_engine.confirm_reservation(db, user.id, reservation_id)
    except reservation_engine.ReservationError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(reservation)
    return reservation


@router.post("/{reservation_id}/cancel", response_model=ReservationOut)
def cancel(reservation_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    try:
        reservation = reservation_engine.cancel_reservation(db, user.id, reservation_id)
    except reservation_engine.ReservationError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(reservation)
    return reservation


@router.post("/{reservation_id}/pay", response_model=PaymentOut, status_code=201)
def pay(reservation_id: int, payload: PaymentCreate, db: Session = Depends(get_db),
        user: User = Depends(get_current_user)):
    from app.models import Reservation
    reservation = db.get(Reservation, reservation_id)
    if not reservation or reservation.user_id != user.id:
        raise HTTPException(404, "Reservation not found")
    resource = db.get(Resource, reservation.resource_id)
    try:
        payment = payment_engine.authorize(
            db, payer_user_id=user.id, payee_user_id=None,
            amount=payload.amount or reservation.amount,
            idempotency_key=payload.idempotency_key,
            reservation_id=reservation.id, fee_percent=resource.fee_percent)
        payment_engine.capture(db, payment)
        reservation.payment_status = "CAPTURED"
    except payment_engine.PaymentError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(payment)
    return payment
