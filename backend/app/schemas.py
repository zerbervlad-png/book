"""API schemas (section 78: frontend receives policies and builds UX accordingly)."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth / Users ----------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = ""


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORMModel):
    id: int
    email: str
    name: str
    role: str
    risk_score: float
    priority_tier: int
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- Organizers ----------

class OrganizerCreate(BaseModel):
    name: str
    description: str = ""


class OrganizerOut(ORMModel):
    id: int
    name: str
    description: str
    is_verified: bool
    default_fee_percent: float
    max_resale_price: int | None


# ---------- Events ----------

class EventCreate(BaseModel):
    title: str
    description: str = ""
    image_url: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    timezone_name: str = "UTC"
    city: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    capacity: int | None = None
    category: str = "OTHER"
    source_url: str | None = None


class EventOut(ORMModel):
    id: int
    title: str
    description: str
    image_url: str | None
    starts_at: datetime
    ends_at: datetime | None
    timezone_name: str
    city: str | None
    address: str | None
    lat: float | None
    lng: float | None
    organizer: OrganizerOut | None
    source: str
    source_url: str | None
    verification_status: str
    last_verified_at: datetime | None
    verification_method: str | None
    status: str
    capacity: int | None
    category: str
    created_at: datetime


class EventVerificationOut(ORMModel):
    id: int
    status: str
    method: str
    source_url: str | None
    notes: str
    checked_at: datetime


class EventReportCreate(BaseModel):
    """Complaint about an incorrect/fake/duplicate queue (TZ section 6)."""
    reason: str  # FAKE_OBJECT | DUPLICATE | WRONG_ADDRESS | CLOSED | SPAM | OTHER
    description: str = ""


class EventReportOut(ORMModel):
    id: int
    event_id: int
    reporter_user_id: int
    reason: str
    description: str
    status: str
    created_at: datetime
    resolved_at: datetime | None


# ---------- Resources ----------

class ResourceCreate(BaseModel):
    event_id: int
    type: str  # ResourceType
    name: str
    capacity: int
    queue_policy: str = "FIFO"
    is_transferable: bool = True
    is_resellable: bool = True
    requires_verification: bool = True
    requires_check_in: bool = True
    requires_organizer_approval: bool = False
    requires_physical_presence: bool = False
    refund_policy: str = "NO_REFUND"
    expiration_policy_seconds: int | None = None
    max_resale_price: int | None = None
    fee_percent: float | None = None
    price_base: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class ResourceOut(ORMModel):
    id: int
    event_id: int
    type: str
    name: str
    capacity: int
    queue_policy: str
    is_transferable: bool
    is_resellable: bool
    requires_verification: bool
    requires_check_in: bool
    requires_organizer_approval: bool
    requires_physical_presence: bool
    gps_optional: bool
    refund_policy: str
    expiration_policy_seconds: int | None
    max_resale_price: int | None
    fee_percent: float | None
    price_base: int
    currency: str
    payload: dict[str, Any]
    created_at: datetime


class AvailabilityOut(BaseModel):
    resource_id: int
    total_capacity: int
    confirmed: int
    available: int
    in_queue: int
    in_waitlist: int
    listed: int
    sold: int
    checked_in: int


class EventInventoryOut(BaseModel):
    """Section 52: marketplace event inventory — all values computed by backend."""
    event_id: int
    total_capacity: int
    confirmed: int
    available: int
    in_queue: int
    in_waitlist: int
    transferable_listed: int
    sold: int
    checked_in: int


# ---------- Access rights ----------

class AccessRightOut(ORMModel):
    id: int
    token_code: str
    kind: str
    resource_id: int
    event_id: int
    queue_id: int | None
    owner_user_id: int | None
    position: int | None
    status: str
    transferable: bool
    resellable: bool
    payload: dict[str, Any]
    created_at: datetime
    expires_at: datetime | None
    used_at: datetime | None


# ---------- Queue ----------

class QueueJoinRequest(BaseModel):
    invite_code: str | None = None
    priority: int = 0


class QueueJoinResult(BaseModel):
    queue_id: int
    membership_id: int
    position: int | None
    access_right: AccessRightOut | None
    message: str


# ---------- Waitlist ----------

class WaitlistEntryOut(ORMModel):
    id: int
    waitlist_id: int
    user_id: int
    position: int
    status: str
    offered_at: datetime | None
    offer_expires_at: datetime | None
    created_at: datetime


# ---------- Reservation ----------

class ReservationCreate(BaseModel):
    resource_id: int
    access_right_id: int | None = None  # e.g. waitlist offer claim
    amount: int = 0


class ReservationOut(ORMModel):
    id: int
    resource_id: int
    user_id: int
    access_right_id: int | None
    status: str
    payment_status: str
    amount: int
    created_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None


# ---------- Listings / Transfers ----------

class ListingCreate(BaseModel):
    access_right_id: int
    price: int | None = None  # None => free transfer offer


class ListingOut(ORMModel):
    id: int
    access_right: AccessRightOut
    seller_user_id: int
    kind: str
    price: int | None
    currency: str
    is_active: bool
    created_at: datetime


class PurchaseQuoteOut(BaseModel):
    """Cost preview for the buyer BEFORE confirming a purchase (TZ sections 3, 9:
    покупатель видит цену и комиссию до оплаты). The fee is withheld from the
    seller's amount, so the buyer pays exactly the listed price."""
    listing_id: int
    kind: str
    price: int | None
    currency: str
    fee_percent: float
    fee_amount: int          # commission withheld by the service
    seller_payout: int | None  # what the seller receives (price − fee)
    buyer_total: int | None    # what the buyer pays (= price, fee from seller)
    deal_window_seconds: int   # time the buyer has to complete the deal


class TransferCreate(BaseModel):
    """Direct transfer (resale) from a listing."""
    listing_id: int
    idempotency_key: str | None = None


class TransferGiftCreate(BaseModel):
    """Direct transfer without listing (section 57: transfer without money)."""
    access_right_id: int
    to_user_email: EmailStr
    idempotency_key: str | None = None


class TransferOut(ORMModel):
    id: int
    access_right_id: int
    from_user_id: int
    to_user_id: int
    kind: str
    price: int | None
    currency: str
    status: str
    created_at: datetime
    completed_at: datetime | None


# ---------- Payments ----------

class PaymentCreate(BaseModel):
    transfer_id: int | None = None
    reservation_id: int | None = None
    amount: int = 0
    idempotency_key: str


class PaymentOut(ORMModel):
    id: int
    transfer_id: int | None
    reservation_id: int | None
    payer_user_id: int
    payee_user_id: int | None
    amount: int
    fee_amount: int
    currency: str
    status: str
    provider: str
    created_at: datetime


# ---------- Check-in ----------

class CheckInRequest(BaseModel):
    token: str  # AT-code, QR payload or one-time code
    method: str = "QR"  # CheckInMethod
    gps: dict[str, Any] = Field(default_factory=dict)  # auxiliary only


class CheckInOut(ORMModel):
    id: int
    access_right_id: int | None
    event_id: int | None
    user_id: int | None
    method: str
    result: str
    presented: str
    checked_at: datetime


# ---------- Disputes ----------

class DisputeCreate(BaseModel):
    transfer_id: int | None = None
    access_right_id: int | None = None
    reason: str
    description: str = ""


class DisputeOut(ORMModel):
    id: int
    transfer_id: int | None
    access_right_id: int | None
    opened_by_user_id: int
    reason: str
    description: str
    status: str
    resolution_notes: str
    created_at: datetime
    resolved_at: datetime | None


# ---------- Notifications ----------

class NotificationOut(ORMModel):
    id: int
    kind: str
    title: str
    body: str
    data: dict[str, Any]
    is_read: bool
    created_at: datetime


# ---------- Marketplace / Search (sections 20, 35) ----------

class MarketplaceItemOut(BaseModel):
    kind: str  # EVENT | LISTING | SLOT
    event: EventOut | None = None
    resource: ResourceOut | None = None
    listing: ListingOut | None = None
    availability: AvailabilityOut | None = None
    quote: PurchaseQuoteOut | None = None  # commission preview for listings


class AuditEventOut(ORMModel):
    id: int
    type: str
    entity_type: str
    entity_id: str
    actor_user_id: int | None
    data: dict[str, Any]
    created_at: datetime


class AnalyticsOut(BaseModel):
    events: int
    queues: int
    registrations: int
    transfers: int
    resales: int
    checkins: int
    disputes: int
    fraud_flags: int
    revenue: int
    conversion: float
    cancellations: int
