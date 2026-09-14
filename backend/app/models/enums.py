"""Domain enumerations — sections 53, 54, 3, 6, 18, 26, 57."""
import enum


class UserRole(str, enum.Enum):
    USER = "USER"
    ORGANIZER = "ORGANIZER"
    ADMIN = "ADMIN"


class EventSource(str, enum.Enum):
    ORGANIZER = "ORGANIZER"        # 5.1
    IMPORT = "IMPORT"              # 5.2 (API / partner / import / official source)
    PARTNER = "PARTNER"
    USER_REQUEST = "USER_REQUEST"  # 5.3


class VerificationStatus(str, enum.Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING_VERIFICATION"
    ORGANIZER_VERIFIED = "ORGANIZER_VERIFIED"
    OFFICIAL = "OFFICIAL"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class EventStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    OPEN = "OPEN"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    QUEUE_OPEN = "QUEUE_OPEN"
    SOLD_OUT = "SOLD_OUT"
    WAITLIST_OPEN = "WAITLIST_OPEN"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    POSTPONED = "POSTPONED"


class ResourceType(str, enum.Enum):
    PHYSICAL_QUEUE = "PHYSICAL_QUEUE"   # 3.1
    EVENT_QUEUE = "EVENT_QUEUE"         # 3.2
    EVENT_REGISTRATION = "EVENT_REGISTRATION"  # 3.3
    WAITLIST = "WAITLIST"               # 3.4
    TIME_SLOT = "TIME_SLOT"             # 3.5
    TICKET = "TICKET"                   # 3.6
    ACCESS_PASS = "ACCESS_PASS"         # 3.7


class QueuePolicy(str, enum.Enum):      # 18
    FIFO = "FIFO"
    RANDOMIZED = "RANDOMIZED"
    LOTTERY = "LOTTERY"
    PRIORITY = "PRIORITY"
    INVITE_ONLY = "INVITE_ONLY"
    HYBRID = "HYBRID"


class AccessRightKind(str, enum.Enum):
    QUEUE_POSITION = "QUEUE_POSITION"
    TICKET = "TICKET"
    SLOT = "SLOT"
    WAITLIST_PRIORITY = "WAITLIST_PRIORITY"
    ACCESS_PASS = "ACCESS_PASS"
    REGISTRATION = "REGISTRATION"


class AccessRightStatus(str, enum.Enum):  # 54
    RESERVED = "RESERVED"
    OWNED = "OWNED"
    LISTED = "LISTED"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    TRANSFERRED = "TRANSFERRED"
    USED = "USED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, enum.Enum):  # 26
    CREATED = "CREATED"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    TRANSFERRED = "TRANSFERRED"


class TransferKind(str, enum.Enum):     # 57 — transfer != resale
    TRANSFER = "TRANSFER"
    RESALE = "RESALE"


class TransferStatus(str, enum.Enum):
    INITIATED = "INITIATED"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    AWAITING_BUYER_CLAIM = "AWAITING_BUYER_CLAIM"
    VERIFYING = "VERIFYING"
    TOKEN_LOCKED = "TOKEN_LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PaymentStatus(str, enum.Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class CheckInMethod(str, enum.Enum):    # 29
    QR = "QR"
    BARCODE = "BARCODE"
    TOKEN = "TOKEN"
    CODE = "CODE"
    MANUAL = "MANUAL"
    API = "API"


class CheckInResult(str, enum.Enum):    # 29
    VALID = "VALID"
    USED = "USED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    INVALID = "INVALID"
    TRANSFERRED = "TRANSFERRED"


class WaitlistEntryStatus(str, enum.Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    PASSED = "PASSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, enum.Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_REFUNDED = "RESOLVED_REFUNDED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    CLOSED = "CLOSED"


class AuditEventType(str, enum.Enum):  # 32
    USER_REGISTERED = "UserRegistered"
    ORGANIZER_VERIFIED = "OrganizerVerified"
    EVENT_CREATED = "EventCreated"
    EVENT_VERIFIED = "EventVerified"
    EVENT_CANCELLED = "EventCancelled"
    EVENT_REPORTED = "EventReported"
    QUEUE_JOINED = "QueueJoined"
    POSITION_ASSIGNED = "PositionAssigned"
    RESERVATION_CREATED = "ReservationCreated"
    RESERVATION_CONFIRMED = "ReservationConfirmed"
    RESERVATION_EXPIRED = "ReservationExpired"
    TRANSFER_CREATED = "TransferCreated"
    LISTING_CREATED = "ListingCreated"
    PAYMENT_AUTHORIZED = "PaymentAuthorized"
    PAYMENT_CAPTURED = "PaymentCaptured"
    REFUND_CREATED = "RefundCreated"
    TRANSFER_COMPLETED = "TransferCompleted"
    TOKEN_INVALIDATED = "TokenInvalidated"
    CHECKIN_COMPLETED = "CheckInCompleted"
    CHECKIN_REJECTED = "CheckInRejected"
    DISPUTE_OPENED = "DisputeOpened"
    FRAUD_FLAGGED = "FraudFlagged"
    ACCESS_RIGHT_CANCELLED = "AccessRightCancelled"
    WALLET_TOPUP = "WalletTopUp"
    DEAL_MESSAGE_SENT = "DealMessageSent"
