"""Queue Engine — sections 8, 9, 18.

Universal policies: FIFO, RANDOMIZED, LOTTERY, PRIORITY, INVITE_ONLY, HYBRID.
A queue can be joined hours before the event; a position is a digital
AccessRight (QueuePosition), not a GPS-derived fact.
"""
import random
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.audit import audit
from app.engines.notify import notify
from app.models import (
    AccessRight, AccessRightKind, AccessRightStatus, AuditEventType, Event, EventStatus, Queue,
    QueueMembership, Resource, utcnow,
)


class QueueEngineError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code


def ensure_queue(db: Session, resource: Resource) -> Queue:
    queue = db.scalar(select(Queue).where(Queue.resource_id == resource.id))
    if queue is None:
        queue = Queue(resource_id=resource.id, policy=resource.queue_policy, is_open=True)
        db.add(queue)
        db.flush()
    return queue


def _next_position(db: Session, queue_id: int) -> int:
    max_pos = db.scalar(
        select(func.max(AccessRight.position)).where(AccessRight.queue_id == queue_id)
    )
    return (max_pos or 0) + 1


def join_queue(
    db: Session, user_id: int, resource: Resource, invite_code: str | None = None, priority: int = 0
) -> tuple[QueueMembership, AccessRight | None]:
    """Join queue; returns membership and (for deterministic policies) the position right."""
    queue = ensure_queue(db, resource)
    event = resource.event

    if event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
        raise QueueEngineError("EVENT_NOT_ACTIVE", "Event is cancelled or completed", 409)
    if not queue.is_open:
        raise QueueEngineError("QUEUE_CLOSED", "Queue is closed", 409)

    existing = db.scalar(
        select(QueueMembership).where(
            QueueMembership.queue_id == queue.id,
            QueueMembership.user_id == user_id,
            QueueMembership.active.is_(True),
        )
    )
    if existing:
        raise QueueEngineError("ALREADY_IN_QUEUE", "User is already in this queue", 409)

    policy = queue.policy

    if policy in ("INVITE_ONLY", "HYBRID"):
        if not invite_code or not _validate_invite(resource, invite_code):
            raise QueueEngineError("INVITE_REQUIRED", "Valid invite code required", 403)

    membership = QueueMembership(
        queue_id=queue.id,
        user_id=user_id,
        priority=priority,
        invite_code=invite_code,
        joined_at=utcnow(),
    )
    db.add(membership)
    db.flush()
    audit(db, AuditEventType.QUEUE_JOINED, "QueueMembership", membership.id,
          actor_user_id=user_id, queue_id=queue.id, resource_id=resource.id, policy=policy)

    access_right = None
    if policy in ("FIFO", "PRIORITY"):
        access_right = _assign_position(db, queue, resource, membership)
    # RANDOMIZED / LOTTERY / HYBRID: position assigned on draw (see draw())
    db.flush()
    return membership, access_right


def _validate_invite(resource: Resource, code: str) -> bool:
    invites = (resource.payload or {}).get("invite_codes") or []
    return code in invites


def _assign_position(
    db: Session, queue: Queue, resource: Resource, membership: QueueMembership
) -> AccessRight:
    position = _next_position(db, queue.id)
    right = AccessRight(
        token_code=_new_token(),
        kind=AccessRightKind.QUEUE_POSITION,
        resource_id=resource.id,
        event_id=resource.event_id,
        queue_id=queue.id,
        owner_user_id=membership.user_id,
        position=position,
        status=AccessRightStatus.OWNED,
        transferable=resource.is_transferable,
        resellable=resource.is_resellable,
        payload={"queue_policy": queue.policy.value},
        one_time_secret=secrets.token_hex(16),
        created_at=utcnow(),
        expires_at=None,
    )
    db.add(right)
    db.flush()
    audit(db, AuditEventType.POSITION_ASSIGNED, "AccessRight", right.id,
          actor_user_id=membership.user_id, queue_id=queue.id, position=position)
    notify(db, membership.user_id, "POSITION_ASSIGNED",
           f"You are #{position} in the queue", resource_id=resource.id, position=position)
    return right


def _new_token() -> str:
    from app.core.security import generate_token_code
    return generate_token_code("AT")


def leave_queue(db: Session, user_id: int, resource: Resource) -> None:
    queue = ensure_queue(db, resource)
    membership = db.scalar(
        select(QueueMembership).where(
            QueueMembership.queue_id == queue.id,
            QueueMembership.user_id == user_id,
            QueueMembership.active.is_(True),
        )
    )
    if not membership:
        raise QueueEngineError("NOT_IN_QUEUE", "User is not in this queue", 404)
    membership.active = False
    right = db.scalar(
        select(AccessRight).where(
            AccessRight.queue_id == queue.id,
            AccessRight.owner_user_id == user_id,
            AccessRight.status.in_([AccessRightStatus.OWNED, AccessRightStatus.LISTED]),
        )
    )
    if right:
        right.status = AccessRightStatus.CANCELLED
        audit(db, AuditEventType.ACCESS_RIGHT_CANCELLED, "AccessRight", right.id,
              actor_user_id=user_id, reason="left_queue")
    db.flush()
    # a freed capacity-based place must reach the waitlist (section 17)
    from app.engines import waitlist as waitlist_engine
    if resource.type.value not in ("PHYSICAL_QUEUE", "EVENT_QUEUE"):
        waitlist_engine.on_capacity_freed(db, resource)


def draw(db: Session, queue: Queue, seed: int | None = None) -> int:
    """Assign positions for RANDOMIZED / LOTTERY queues (called manually or by scheduler)."""
    rng = random.Random(seed)
    memberships = db.scalars(
        select(QueueMembership).where(
            QueueMembership.queue_id == queue.id, QueueMembership.active.is_(True)
        )
    ).all()
    pending = [m for m in memberships if not db.scalar(
        select(func.count(AccessRight.id)).where(
            AccessRight.queue_id == queue.id, AccessRight.owner_user_id == m.user_id))
    ]
    if queue.policy.value in ("RANDOMIZED", "LOTTERY"):
        rng.shuffle(pending)
    elif queue.policy.value == "HYBRID":
        pending.sort(key=lambda m: (-m.priority, rng.random()))
    count = 0
    for membership in pending:
        _assign_position(db, queue, queue.resource, membership)
        count += 1
    queue.drawn_at = utcnow()
    db.flush()
    return count


def predicted_position(db: Session, queue_id: int) -> int:
    """Predicted position shown before draw for non-deterministic policies."""
    return db.scalar(
        select(func.count(QueueMembership.id)).where(
            QueueMembership.queue_id == queue_id, QueueMembership.active.is_(True))
    ) or 0
