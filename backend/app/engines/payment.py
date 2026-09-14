"""Payment Engine — sections 27, 61.

Payments are escrow ledger operations decoupled from queues: they work with
tickets, slots, positions, registrations, transfer and resale alike.
Idempotency: the same idempotency_key never creates a second payment.
Provider abstraction allows attaching a real PSP (Stripe/ЮKassa) later —
see docs/architecture.md.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.audit import audit
from app.models import (
    AuditEventType, Payment, PaymentStatus, Reservation, Transfer, UserBalance, utcnow,
)
from app.core.config import settings


class PaymentError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def _balance(db: Session, user_id: int) -> UserBalance:
    balance = db.scalar(select(UserBalance).where(UserBalance.user_id == user_id))
    if balance is None:
        balance = UserBalance(user_id=user_id)
        db.add(balance)
        db.flush()
    return balance


def compute_fee(amount: int, fee_percent: float | None) -> int:
    percent = settings.DEFAULT_PLATFORM_FEE_PERCENT if fee_percent is None else fee_percent
    # exact decimal math — float arithmetic produces off-by-one fees
    # (e.g. 1450 * 5.7 / 100.0 == 82.64999...), and the fee is always
    # rounded toward the payer's protection (down)
    from decimal import Decimal, ROUND_FLOOR
    fee = (Decimal(amount) * Decimal(str(percent)) / Decimal(100))
    return int(fee.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def authorize(
    db: Session,
    payer_user_id: int,
    payee_user_id: int | None,
    amount: int,
    idempotency_key: str,
    transfer_id: int | None = None,
    reservation_id: int | None = None,
    fee_percent: float | None = None,
) -> Payment:
    if amount < 0:
        raise PaymentError("INVALID_AMOUNT", "Amount must be non-negative", 400)

    existing = db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
    if existing:
        return existing  # idempotent — section 61

    payer_balance = _balance(db, payer_user_id)
    if payer_balance.available < amount:
        # a payment must never silently drive the balance negative
        if not settings.WALLET_AUTO_TOPUP:
            raise PaymentError("INSUFFICIENT_FUNDS",
                               "Not enough money in the wallet — top up first", 402)
        # demo mode: instant mock top-up (a real PSP replaces this later)
        topup_amount = max(amount - payer_balance.available, 10_000)
        payer_balance.available += topup_amount
        audit(db, AuditEventType.WALLET_TOPUP, "UserBalance", payer_user_id,
              actor_user_id=payer_user_id, demo_topup=topup_amount)
    payer_balance.available -= amount       # debit payer
    payer_balance.escrow += amount         # hold in escrow
    if payee_user_id is not None:
        payee_balance = _balance(db, payee_user_id)
        payee_balance.escrow += amount

    fee_amount = compute_fee(amount, fee_percent)
    payment = Payment(
        transfer_id=transfer_id,
        reservation_id=reservation_id,
        payer_user_id=payer_user_id,
        payee_user_id=payee_user_id,
        amount=amount,
        fee_amount=fee_amount,
        status=PaymentStatus.AUTHORIZED,
        idempotency_key=idempotency_key,
        created_at=utcnow(),
    )
    db.add(payment)
    db.flush()
    audit(db, AuditEventType.PAYMENT_AUTHORIZED, "Payment", payment.id,
          actor_user_id=payer_user_id, amount=amount, transfer_id=transfer_id,
          reservation_id=reservation_id)
    return payment


def capture(db: Session, payment: Payment) -> Payment:
    """Move escrow to the payee (minus platform fee)."""
    if payment.status == PaymentStatus.CAPTURED:
        return payment  # idempotent
    if payment.status != PaymentStatus.AUTHORIZED:
        raise PaymentError("INVALID_STATE", f"Payment is {payment.status.value}", 409)

    payer_balance = _balance(db, payment.payer_user_id)
    payer_balance.escrow -= payment.amount
    if payment.payee_user_id is not None:
        payee_balance = _balance(db, payment.payee_user_id)
        payee_balance.escrow -= payment.amount
        payee_balance.available += payment.amount - payment.fee_amount

    payment.status = PaymentStatus.CAPTURED
    payment.captured_at = utcnow()
    db.flush()
    audit(db, AuditEventType.PAYMENT_CAPTURED, "Payment", payment.id,
          actor_user_id=payment.payer_user_id, amount=payment.amount)
    return payment


def refund(db: Session, payment: Payment) -> Payment:
    if payment.status == PaymentStatus.REFUNDED:
        return payment  # idempotent
    if payment.status != PaymentStatus.CAPTURED:
        raise PaymentError("INVALID_STATE", "Only captured payments can be refunded", 409)

    payer_balance = _balance(db, payment.payer_user_id)
    payer_balance.available += payment.amount
    # the payer's escrow was already released at capture time — refunding must
    # not touch it again (a second decrement would eat into escrow held for
    # the payer's other in-flight payments)
    if payment.payee_user_id is not None:
        payee_balance = _balance(db, payment.payee_user_id)
        payee_balance.available -= payment.amount - payment.fee_amount

    payment.status = PaymentStatus.REFUNDED
    payment.refunded_at = utcnow()
    db.flush()
    audit(db, AuditEventType.REFUND_CREATED, "Payment", payment.id,
          actor_user_id=payment.payer_user_id, amount=payment.amount)
    return payment


def fail(db: Session, payment: Payment) -> Payment:
    if payment.status != PaymentStatus.AUTHORIZED:
        raise PaymentError("INVALID_STATE", "Only authorized payments can fail", 409)
    payer_balance = _balance(db, payment.payer_user_id)
    payer_balance.available += payment.amount
    payer_balance.escrow -= payment.amount
    if payment.payee_user_id is not None:
        payee_balance = _balance(db, payment.payee_user_id)
        payee_balance.escrow -= payment.amount
    payment.status = PaymentStatus.FAILED
    db.flush()
    return payment
