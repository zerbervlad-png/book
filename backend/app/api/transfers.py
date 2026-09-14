"""Transfers & listings API — sections 13-16, 19, 50, 51, 56-58, 61.

Marketplace listings + direct transfers + resale payments with idempotency.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines import audit as audit_engine
from app.engines import fraud, transfer as transfer_engine
from app.engines.notify import notify
from app.models import DealMessage, Listing, Resource, Transfer, User
from app.models import AuditEventType
from app.schemas import (
    DealMessageCreate, DealMessageOut, ListingCreate, ListingOut, PaymentCreate,
    PaymentOut, PurchaseQuoteOut, TransferCreate, TransferGiftCreate, TransferOut,
)

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.get("/listings", response_model=list[ListingOut])
def browse_listings(resource_id: int | None = None, db: Session = Depends(get_db),
                    user: User | None = Depends(get_current_user)):
    stmt = select(Listing).where(Listing.is_active.is_(True))
    if resource_id:
        stmt = stmt.where(Listing.access_right.has(resource_id=resource_id))
    return db.scalars(stmt.order_by(Listing.created_at.desc())).all()


@router.post("/listings", response_model=ListingOut, status_code=201)
def create_listing(payload: ListingCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    from app.models import AccessRight
    right = db.get(AccessRight, payload.access_right_id)
    if right:
        try:
            fraud.guard_listing_of_used_right(db, right)
        except fraud.FraudError as e:
            raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    try:
        listing = transfer_engine.create_listing(
            db, user.id, payload.access_right_id, payload.price)
    except transfer_engine.TransferError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(listing)
    return listing


@router.post("/listings/{listing_id}/cancel", response_model=ListingOut)
def cancel_listing(listing_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    try:
        listing = transfer_engine.cancel_listing(db, user.id, listing_id)
    except transfer_engine.TransferError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(listing)
    return listing


@router.get("/listings/{listing_id}/quote", response_model=PurchaseQuoteOut)
def listing_quote(listing_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Cost preview: price, commission and payout BEFORE the buyer confirms (TZ 3, 9)."""
    listing = db.get(Listing, listing_id)
    if not listing or not listing.is_active:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Listing not found"})
    return PurchaseQuoteOut(**transfer_engine.quote_listing(db, listing))


@router.post("/buy", response_model=TransferOut, status_code=201)
def buy_from_listing(payload: TransferCreate, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    try:
        transfer = transfer_engine.initiate_from_listing(
            db, user.id, payload.listing_id, payload.idempotency_key)
    except transfer_engine.TransferError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/gift", response_model=TransferOut, status_code=201)
def gift(payload: TransferGiftCreate, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    try:
        transfer = transfer_engine.initiate_gift(
            db, user.id, payload.access_right_id, payload.to_user_email,
            payload.idempotency_key)
    except transfer_engine.TransferError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{transfer_id}/pay", response_model=PaymentOut, status_code=201)
def pay_transfer(transfer_id: int, payload: PaymentCreate,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        transfer, payment = transfer_engine.pay_for_transfer(
            db, user.id, transfer_id, payload.idempotency_key)
    except transfer_engine.TransferError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    if payment:
        db.refresh(payment)
        return payment
    from app.models import Payment
    existing = db.scalar(select(Payment).where(Payment.transfer_id == transfer_id))
    if existing:
        return existing
    raise HTTPException(409, detail={"code": "PAYMENT_NOT_REQUIRED",
                                     "message": "Transfer does not require payment"})


@router.post("/{transfer_id}/approve", response_model=TransferOut)
def approve(transfer_id: int, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    try:
        transfer = transfer_engine.approve_transfer(db, user.id, transfer_id)
    except transfer_engine.TransferError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{transfer_id}/cancel", response_model=TransferOut)
def cancel(transfer_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    try:
        transfer = transfer_engine.cancel_transfer(db, user.id, transfer_id)
    except transfer_engine.TransferError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    db.refresh(transfer)
    return transfer


@router.get("/my", response_model=list[TransferOut])
def my_transfers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    transfer_engine.sweep_expired(db)
    # sweeping expires transfers and refunds captured payments — persist it
    db.commit()
    return db.scalars(select(Transfer).where(
        (Transfer.from_user_id == user.id) | (Transfer.to_user_id == user.id)
    ).order_by(Transfer.created_at.desc())).all()


# ---------- deal chat (buyer ↔ seller agree where/when to meet) ----------

def _chat_transfer_or_403(db: Session, transfer_id: int, user: User) -> Transfer:
    transfer = db.get(Transfer, transfer_id)
    if not transfer:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Transfer not found"})
    if user.id not in (transfer.from_user_id, transfer.to_user_id) \
            and user.role.value != "ADMIN":
        raise HTTPException(403, detail={"code": "NOT_PARTICIPANT",
                                         "message": "Only the deal participants can use this chat"})
    return transfer


@router.get("/{transfer_id}/messages", response_model=list[DealMessageOut])
def get_messages(transfer_id: int, after_id: int = 0,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _chat_transfer_or_403(db, transfer_id, user)
    stmt = select(DealMessage).where(
        DealMessage.transfer_id == transfer_id, DealMessage.id > after_id
    ).order_by(DealMessage.id)
    return db.scalars(stmt).all()


@router.post("/{transfer_id}/messages", response_model=DealMessageOut, status_code=201)
def send_message(transfer_id: int, payload: DealMessageCreate,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    transfer = _chat_transfer_or_403(db, transfer_id, user)
    body = payload.body.strip()
    if not body:
        raise HTTPException(422, detail={"code": "EMPTY_MESSAGE",
                                        "message": "Message must not be empty"})
    message = DealMessage(
        transfer_id=transfer_id,
        sender_user_id=user.id,
        body=body,
    )
    db.add(message)
    db.flush()
    # push a notification so the counterpart sees the message
    counterpart_id = transfer.to_user_id if user.id == transfer.from_user_id \
        else transfer.from_user_id
    notify(db, counterpart_id, "DEAL_MESSAGE",
           "Новое сообщение по сделке", payload.body[:120], transfer_id=transfer_id)
    audit_engine.audit(db, AuditEventType.DEAL_MESSAGE_SENT, "DealMessage", message.id,
                       actor_user_id=user.id, transfer_id=transfer_id)
    db.commit()
    db.refresh(message)
    return message
