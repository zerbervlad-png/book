"""Domain entities — section 76 DOMAIN MODEL.

User, Organizer, Event, Resource, AccessModel(policy), Availability (computed),
Queue, QueuePosition (as AccessRight kind), Waitlist, Ticket (as AccessRight kind
with payload), AccessPass, Reservation, Transfer, Payment, CheckIn, Verification,
Dispute, AuditEvent.

Design decisions per the TZ:
- AccessRight is the universal digital token (sections 9, 12, 50): it carries an
  AT-code, owner, status, transfer rules and kind-specific payload.
- Queue positions, tickets, slots and waitlist priorities are AccessRights of
  different kinds -> one Ownership/Transfer/Payment/CheckIn pipeline for all.
- GPS is never a proof of queue membership (section 10): telemetry is stored as
  an auxiliary signal only.
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    AccessRightKind, AccessRightStatus, AuditEventType, CheckInMethod, CheckInResult,
    DisputeStatus, EventSource, EventStatus, PaymentStatus, QueuePolicy, ReservationStatus,
    ResourceType, TransferKind, TransferStatus, UserRole, VerificationStatus,
    WaitlistEntryStatus,
)


def utcnow() -> datetime:
    """Naive-UTC convention: SQLite drops tzinfo, so all timestamps are
    stored and compared as naive UTC (documented in README; for PostgreSQL
    use a fixed timezone adapter)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)     # 31: fraud scoring
    priority_tier: Mapped[int] = mapped_column(Integer, default=0)  # 18: PRIORITY policy
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organizer: Mapped["Organizer | None"] = relationship(back_populates="user", uselist=False)


class Organizer(Base):
    __tablename__ = "organizers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # 6: Organizer Verified
    default_fee_percent: Mapped[float] = mapped_column(Float, default=0.0)
    max_resale_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 58
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="organizer")
    events: Mapped[list["Event"]] = relationship(back_populates="organizer")


class Event(Base):
    """Primary object — section 4. Exists before the physical occurrence."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(64), default="UTC")  # 36
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)   # optional, never required
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    organizer_id: Mapped[int | None] = mapped_column(ForeignKey("organizers.id"), nullable=True)
    source: Mapped[EventSource] = mapped_column(Enum(EventSource), default=EventSource.ORGANIZER)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # 6
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus), default=VerificationStatus.UNVERIFIED)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), default=EventStatus.DRAFT)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str] = mapped_column(String(64), default="OTHER")  # 35: search by category
    canonical_key: Mapped[str] = mapped_column(String(512), index=True)  # 69/70: dedup
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organizer: Mapped[Organizer | None] = relationship(back_populates="events")
    resources: Mapped[list["Resource"]] = relationship(back_populates="event")
    verifications: Mapped[list["EventVerification"]] = relationship(back_populates="event")


class Resource(Base):
    """Resource adapter data — sections 3, 39, 40. Access policies per section 55."""
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    type: Mapped[ResourceType] = mapped_column(Enum(ResourceType))
    name: Mapped[str] = mapped_column(String(255))
    capacity: Mapped[int] = mapped_column(Integer)
    queue_policy: Mapped[QueuePolicy] = mapped_column(Enum(QueuePolicy), default=QueuePolicy.FIFO)
    # 55: ACCESS POLICY
    is_transferable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_resellable: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_verification: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_check_in: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_organizer_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_physical_presence: Mapped[bool] = mapped_column(Boolean, default=False)  # GPS optional
    gps_optional: Mapped[bool] = mapped_column(Boolean, default=True)  # 10: GPS is auxiliary
    refund_policy: Mapped[str] = mapped_column(String(64), default="NO_REFUND")
    expiration_policy_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_resale_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 58
    fee_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_base: Mapped[int] = mapped_column(Integer, default=0)  # base price in minor units
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # slot grid, seating, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event: Mapped[Event] = relationship(back_populates="resources")
    queues: Mapped[list["Queue"]] = relationship(back_populates="resource")
    waitlist: Mapped["Waitlist | None"] = relationship(back_populates="resource", uselist=False)
    access_rights: Mapped[list["AccessRight"]] = relationship(back_populates="resource")


class Queue(Base):
    __tablename__ = "queues"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    policy: Mapped[QueuePolicy] = mapped_column(Enum(QueuePolicy), default=QueuePolicy.FIFO)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # lottery/randomized

    resource: Mapped[Resource] = relationship(back_populates="queues")
    memberships: Mapped[list["QueueMembership"]] = relationship(back_populates="queue")


class QueueMembership(Base):
    """Raw membership before/without a position (e.g. lottery awaiting draw)."""
    __tablename__ = "queue_memberships"
    __table_args__ = (UniqueConstraint("queue_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    invite_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    queue: Mapped[Queue] = relationship(back_populates="memberships")


class AccessRight(Base):
    """Universal digital token — sections 9, 12, 50, 88 (ACCESS RIGHT)."""
    __tablename__ = "access_rights"
    __table_args__ = (
        Index("ix_access_rights_resource_owner", "resource_id", "owner_user_id"),
        Index("ix_access_rights_token", "token_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # AT-938283
    kind: Mapped[AccessRightKind] = mapped_column(Enum(AccessRightKind))
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    queue_id: Mapped[int | None] = mapped_column(ForeignKey("queues.id"), nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 9: QueuePosition
    status: Mapped[AccessRightStatus] = mapped_column(
        Enum(AccessRightStatus), default=AccessRightStatus.OWNED)
    transferable: Mapped[bool] = mapped_column(Boolean, default=True)
    resellable: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # seat, slot time, qr secret, etc.
    one_time_secret: Mapped[str] = mapped_column(String(64), default="")  # QR/one-time code seed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resource: Mapped[Resource] = relationship(back_populates="access_rights")
    transfers: Mapped[list["Transfer"]] = relationship(back_populates="access_right")
    checkins: Mapped[list["CheckIn"]] = relationship(back_populates="access_right")


class Waitlist(Base):
    __tablename__ = "waitlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), unique=True, index=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True)

    resource: Mapped[Resource] = relationship(back_populates="waitlist")
    entries: Mapped[list["WaitlistEntry"]] = relationship(
        back_populates="waitlist", order_by="WaitlistEntry.position")


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"
    __table_args__ = (UniqueConstraint("waitlist_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    waitlist_id: Mapped[int] = mapped_column(ForeignKey("waitlists.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[WaitlistEntryStatus] = mapped_column(
        Enum(WaitlistEntryStatus), default=WaitlistEntryStatus.WAITING)
    offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 17
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    waitlist: Mapped[Waitlist] = relationship(back_populates="entries")


class Reservation(Base):
    """Section 26. Separate object with TTL."""
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    access_right_id: Mapped[int | None] = mapped_column(ForeignKey("access_rights.id"), nullable=True)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus), default=ReservationStatus.CREATED)
    payment_status: Mapped[str] = mapped_column(String(32), default="NONE")
    amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    access_right: Mapped[AccessRight | None] = relationship()


class Listing(Base):
    """Marketplace listing (pre-event marketplace — section 51)."""
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    access_right_id: Mapped[int] = mapped_column(ForeignKey("access_rights.id"), unique=True, index=True)
    seller_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[TransferKind] = mapped_column(Enum(TransferKind), default=TransferKind.RESALE)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None => free transfer
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    access_right: Mapped[AccessRight] = relationship()


class Transfer(Base):
    """Sections 13, 14, 15, 16, 56, 57, 61. Escrow state machine protecting against double spending."""
    __tablename__ = "transfers"
    __table_args__ = (
        # At most ONE open transfer per access right — enforced by the database,
        # making simultaneous purchases impossible even under races (13, 61).
        Index(
            "uq_open_transfer_per_right", "access_right_id", unique=True,
            sqlite_where=text(
                "status IN ('INITIATED','AWAITING_PAYMENT','AWAITING_BUYER_CLAIM',"
                "'VERIFYING','TOKEN_LOCKED')"),
            postgresql_where=text(
                "status IN ('INITIATED','AWAITING_PAYMENT','AWAITING_BUYER_CLAIM',"
                "'VERIFYING','TOKEN_LOCKED')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    access_right_id: Mapped[int] = mapped_column(ForeignKey("access_rights.id"), index=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[TransferKind] = mapped_column(Enum(TransferKind))
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    status: Mapped[TransferStatus] = mapped_column(Enum(TransferStatus), default=TransferStatus.INITIATED)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    access_right: Mapped[AccessRight] = relationship(back_populates="transfers")
    payments: Mapped[list["Payment"]] = relationship(back_populates="transfer")


class Payment(Base):
    """Section 27. Ledger escrow payments, not tied to queues only."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfers.id"), nullable=True, index=True)
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservations.id"), nullable=True, index=True)
    payer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    payee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    fee_amount: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.AUTHORIZED)
    provider: Mapped[str] = mapped_column(String(32), default="ledger_escrow")
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)  # 61
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    transfer: Mapped[Transfer | None] = relationship(back_populates="payments")


class CheckIn(Base):
    """Section 29. Universal check-in engine with results."""
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(primary_key=True)
    access_right_id: Mapped[int | None] = mapped_column(ForeignKey("access_rights.id"), index=True, nullable=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), index=True, nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    method: Mapped[CheckInMethod] = mapped_column(Enum(CheckInMethod))
    result: Mapped[CheckInResult] = mapped_column(Enum(CheckInResult))
    presented: Mapped[str] = mapped_column(String(128), default="")  # token/code presented
    checked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    gps: Mapped[dict] = mapped_column(JSON, default=dict)  # auxiliary only (10, 49)

    access_right: Mapped[AccessRight | None] = relationship(back_populates="checkins")


class EventVerification(Base):
    """Sections 6, 7. Event Verification Engine records."""
    __tablename__ = "event_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    status: Mapped[VerificationStatus] = mapped_column(Enum(VerificationStatus))
    method: Mapped[str] = mapped_column(String(64))  # organizer/official/duplicate-check/heuristic
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    event: Mapped[Event] = relationship(back_populates="verifications")


class Dispute(Base):
    """Section 28."""
    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfers.id"), nullable=True, index=True)
    access_right_id: Mapped[int | None] = mapped_column(ForeignKey("access_rights.id"), nullable=True, index=True)
    opened_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[DisputeStatus] = mapped_column(Enum(DisputeStatus), default=DisputeStatus.OPEN)
    resolution_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Sections 32, 33. Append-only, never edited by users."""
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[AuditEventType] = mapped_column(Enum(AuditEventType))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    """Section 61: repeated requests must not create a second operation."""
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(255))
    response_status: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserTelemetry(Base):
    """GPS is auxiliary only (sections 10, 49, 65) — recommendations/anomalies, never proof."""
    __tablename__ = "user_telemetry"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_spoof_suspect: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserBalance(Base):
    """Ledger balances for escrow payments (section 27)."""
    __tablename__ = "user_balances"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    available: Mapped[int] = mapped_column(Integer, default=0)   # minor units, can be negative for payers
    escrow: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    """Section 44."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
