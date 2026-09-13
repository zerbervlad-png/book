"""Transfer Engine — sections 13, 14, 15, 16, 56, 57, 61.

Pipeline (13): TRANSFER INITIATED → PAYMENT → VERIFICATION → TOKEN LOCK →
NEW OWNER → OLD OWNER INVALIDATED.

Double-spend protection: an AccessRight can be in TRANSFER_PENDING for at most
one transfer; concurrent attempts are rejected with a row-level guard.
"""
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_token_code
from app.engines import payment as payment_engine
from app.engines.audit import audit
from app.engines.notify import notify
from app.models import (
    AccessRight, AccessRightStatus, AuditEventType, Listing, Transfer, TransferKind,
    TransferStatus, User, utcnow,
)


class TransferError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def create_listing(db: Session, seller_id: int, access_right_id: int,
                   price: int | None) -> Listing:
    right = _get_owned_right(db, seller_id, access_right_id)
    resource = right.resource
    if not resource.is_transferable:
        raise TransferError("TRANSFER_FORBIDDEN", "Organizer disabled transfer for this resource", 403)
    if price is not None:
        if not resource.is_resellable:
            raise TransferError("RESALE_FORBIDDEN", "Organizer disabled resale for this resource", 403)
        if resource.max_resale_price is not None and price > resource.max_resale_price:
            raise TransferError("PRICE_TOO_HIGH",
                                f"Max resale price is {resource.max_resale_price}", 400)
    if right.status != AccessRightStatus.OWNED:
        raise TransferError("INVALID_STATE",
                            f"Right is {right.status.value}, cannot list", 409)

    existing = db.scalar(select(Listing).where(
        Listing.access_right_id == access_right_id, Listing.is_active.is_(True)))
    if existing:
        raise TransferError("ALREADY_LISTED", "Right is already listed", 409)

    listing = Listing(
        access_right_id=access_right_id,
        seller_user_id=seller_id,
        kind=TransferKind.RESALE if price is not None else TransferKind.TRANSFER,
        price=price,
        created_at=utcnow(),
    )
    right.status = AccessRightStatus.LISTED
    db.add(listing)
    db.flush()
    audit(db, AuditEventType.LISTING_CREATED, "Listing", listing.id,
          actor_user_id=seller_id, access_right_id=access_right_id, price=price)
    return listing


def cancel_listing(db: Session, seller_id: int, listing_id: int) -> Listing:
    listing = db.get(Listing, listing_id)
    if not listing or listing.seller_user_id != seller_id or not listing.is_active:
        raise TransferError("NOT_FOUND", "Listing not found", 404)
    if listing.access_right.status != AccessRightStatus.LISTED:
        raise TransferError("INVALID_STATE", "Listing is not in LISTED state", 409)
    listing.is_active = False
    listing.closed_at = utcnow()
    listing.access_right.status = AccessRightStatus.OWNED
    db.flush()
    return listing


def initiate_from_listing(db: Session, buyer_id: int, listing_id: int,
                          idempotency_key: str | None) -> Transfer:
    listing = db.get(Listing, listing_id)
    if not listing or not listing.is_active:
        raise TransferError("NOT_FOUND", "Listing not found", 404)
    if listing.seller_user_id == buyer_id:
        raise TransferError("SELF_TRANSFER", "Cannot buy own listing", 400)

    if idempotency_key:
        existing = db.scalar(select(Transfer).where(Transfer.idempotency_key == idempotency_key))
        if existing:
            return existing  # idempotent

    return _initiate(db, listing.access_right, buyer_id, listing.kind,
                     listing.price, idempotency_key)


def initiate_gift(db: Session, from_user_id: int, access_right_id: int,
                  to_user_email: str, idempotency_key: str | None) -> Transfer:
    right = _get_owned_right(db, from_user_id, access_right_id)
    if not right.resource.is_transferable:
        raise TransferError("TRANSFER_FORBIDDEN", "Organizer disabled transfer", 403)
    to_user = db.scalar(select(User).where(User.email == to_user_email))
    if not to_user:
        raise TransferError("USER_NOT_FOUND", "Recipient not found", 404)
    if to_user.id == from_user_id:
        raise TransferError("SELF_TRANSFER", "Cannot transfer to yourself", 400)
    if idempotency_key:
        existing = db.scalar(select(Transfer).where(Transfer.idempotency_key == idempotency_key))
        if existing:
            return existing
    return _initiate(db, right, to_user.id, TransferKind.TRANSFER, None, idempotency_key)


def _get_owned_right(db: Session, user_id: int, access_right_id: int) -> AccessRight:
    right = db.get(AccessRight, access_right_id)
    if not right:
        raise TransferError("NOT_FOUND", "Access right not found", 404)
    if right.owner_user_id != user_id:
        raise TransferError("NOT_OWNER", "You do not own this access right", 403)
    return right


def _initiate(db: Session, right: AccessRight, buyer_id: int, kind: TransferKind,
              price: int | None, idempotency_key: str | None) -> Transfer:
    # ---- double-spend guard: only LISTED/OWNED rights can enter transfer ----
    if right.status not in (AccessRightStatus.OWNED, AccessRightStatus.LISTED):
        raise TransferError("RIGHT_NOT_TRANSFERABLE",
                            f"Right is {right.status.value}", 409)

    right.status = AccessRightStatus.TRANSFER_PENDING  # token lock (13)
    transfer = Transfer(
        access_right_id=right.id,
        from_user_id=right.owner_user_id,
        to_user_id=buyer_id,
        kind=kind,
        price=price,
        currency=right.resource.currency,
        status=TransferStatus.INITIATED,
        idempotency_key=idempotency_key,
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(seconds=settings.TRANSFER_TTL_SECONDS),
    )
    db.add(transfer)
    from sqlalchemy.exc import IntegrityError
    try:
        db.flush()  # unique partial index enforces single open transfer (13)
    except IntegrityError:
        db.rollback()
        raise TransferError("RIGHT_NOT_TRANSFERABLE",
                            "Access right is already being transferred", 409)
    audit(db, AuditEventType.TRANSFER_CREATED, "Transfer", transfer.id,
          actor_user_id=buyer_id, access_right_id=right.id,
          from_user=transfer.from_user_id, to_user=transfer.to_user_id, price=price)
    notify(db, transfer.from_user_id, "TRANSFER_INITIATED",
           "Transfer initiated", transfer_id=transfer.id)
    if price is None:
        # free transfer: complete immediately
        complete_transfer(db, transfer.id, None)
        db.refresh(transfer)
    else:
        transfer.status = TransferStatus.AWAITING_PAYMENT
    return transfer


def pay_for_transfer(db: Session, buyer_id: int, transfer_id: int,
                     idempotency_key: str) -> tuple:
    """Authorize + capture payment and complete the transfer atomically."""
    transfer = db.get(Transfer, transfer_id)
    if not transfer:
        raise TransferError("NOT_FOUND", "Transfer not found", 404)
    if transfer.to_user_id != buyer_id:
        raise TransferError("NOT_BUYER", "Only the buyer can pay for this transfer", 403)
    if transfer.status == TransferStatus.COMPLETED:
        payment = db.scalar(select(payment_engine.Payment).where(
            payment_engine.Payment.transfer_id == transfer.id))
        return transfer, payment  # idempotent
    if transfer.status != TransferStatus.AWAITING_PAYMENT:
        raise TransferError("INVALID_STATE",
                            f"Transfer is {transfer.status.value}", 409)

    fee_percent = transfer.access_right.resource.fee_percent
    pay = payment_engine.authorize(
        db, payer_user_id=buyer_id, payee_user_id=transfer.from_user_id,
        amount=transfer.price or 0, idempotency_key=idempotency_key,
        transfer_id=transfer.id, fee_percent=fee_percent)
    payment_engine.capture(db, pay)

    transfer.status = TransferStatus.VERIFYING
    db.flush()

    # verification step (policy-driven): organizer approval if required
    resource = transfer.access_right.resource
    if resource.requires_organizer_approval:
        transfer.status = TransferStatus.AWAITING_BUYER_CLAIM  # pending organizer approval
        db.flush()
        organizer = resource.event.organizer
        if organizer:
            notify(db, organizer.user_id, "APPROVAL_REQUIRED",
                   "Transfer awaiting organizer approval", transfer_id=transfer.id)
    else:
        complete_transfer(db, transfer.id, pay.id)
    db.refresh(transfer)
    return transfer, pay


def approve_transfer(db: Session, organizer_user_id: int, transfer_id: int) -> Transfer:
    transfer = db.get(Transfer, transfer_id)
    if not transfer:
        raise TransferError("NOT_FOUND", "Transfer not found", 404)
    right = transfer.access_right
    organizer = right.resource.event.organizer
    if not organizer or organizer.user_id != organizer_user_id:
        raise TransferError("FORBIDDEN", "Only the event organizer can approve", 403)
    if transfer.status != TransferStatus.AWAITING_BUYER_CLAIM:
        raise TransferError("INVALID_STATE", "Transfer is not awaiting approval", 409)
    complete_transfer(db, transfer.id, None)
    return db.get(Transfer, transfer_id)


def complete_transfer(db: Session, transfer_id: int, payment_id: int | None) -> Transfer:
    """TOKEN LOCK → NEW OWNER → OLD OWNER INVALIDATED (section 13)."""
    transfer = db.get(Transfer, transfer_id)
    right = transfer.access_right
    if right.owner_user_id != transfer.from_user_id:
        raise TransferError("DOUBLE_SPEND",
                            "Access right already belongs to another user", 409)

    old_token = right.token_code
    # issue a NEW token to the new owner; old one is invalidated
    right.owner_user_id = transfer.to_user_id
    right.token_code = generate_token_code("AT")
    right.one_time_secret = secrets.token_hex(16)
    right.status = AccessRightStatus.OWNED
    right.transferable = right.resource.is_transferable
    right.resellable = right.resource.is_resellable

    transfer.status = TransferStatus.COMPLETED
    transfer.completed_at = utcnow()

    # deactivate listing if any
    listing = db.scalar(select(Listing).where(
        Listing.access_right_id == right.id, Listing.is_active.is_(True)))
    if listing:
        listing.is_active = False
        listing.closed_at = utcnow()

    audit(db, AuditEventType.TRANSFER_COMPLETED, "Transfer", transfer.id,
          actor_user_id=transfer.to_user_id, access_right_id=right.id,
          old_token=old_token, new_token=right.token_code)
    audit(db, AuditEventType.TOKEN_INVALIDATED, "AccessRight", right.id,
          actor_user_id=transfer.from_user_id, invalidated_token=old_token)
    notify(db, transfer.to_user_id, "TRANSFER_COMPLETED",
           "Access right is now yours", access_right_id=right.id)
    notify(db, transfer.from_user_id, "TRANSFER_COMPLETED",
           "Your access right was transferred", access_right_id=right.id)
    db.flush()
    return transfer


def cancel_transfer(db: Session, user_id: int, transfer_id: int) -> Transfer:
    transfer = db.get(Transfer, transfer_id)
    if not transfer:
        raise TransferError("NOT_FOUND", "Transfer not found", 404)
    if user_id not in (transfer.from_user_id, transfer.to_user_id):
        raise TransferError("FORBIDDEN", "Not a participant of this transfer", 403)
    if transfer.status == TransferStatus.COMPLETED:
        raise TransferError("INVALID_STATE", "Transfer already completed", 409)
    right = transfer.access_right
    if right.status == AccessRightStatus.TRANSFER_PENDING and \
            right.owner_user_id == transfer.from_user_id:
        right.status = AccessRightStatus.OWNED
    transfer.status = TransferStatus.CANCELLED
    # refund a captured payment so the buyer never loses money on a
    # cancelled/expired transfer (sections 27, 28)
    payment = db.scalar(select(payment_engine.Payment).where(
        payment_engine.Payment.transfer_id == transfer.id))
    if payment and payment.status == payment_engine.PaymentStatus.CAPTURED:
        payment_engine.refund(db, payment)
    db.flush()
    return transfer


def sweep_expired(db: Session) -> int:
    now = utcnow()
    stale = db.scalars(select(Transfer).where(
        Transfer.status.in_([TransferStatus.INITIATED, TransferStatus.AWAITING_PAYMENT,
                             TransferStatus.AWAITING_BUYER_CLAIM]),
        Transfer.expires_at < now,
    )).all()
    for transfer in stale:
        cancel_transfer(db, transfer.from_user_id, transfer.id)
    return len(stale)
