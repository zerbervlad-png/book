"""Queues API — sections 8, 9, 18, 30."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines import fraud, queue_engine
from app.models import Event, EventStatus, Queue, QueueMembership, Resource, User
from app.schemas import AccessRightOut, QueueJoinRequest, QueueJoinResult

router = APIRouter(prefix="/queues", tags=["queues"])


def _load_resource(db: Session, resource_id: int) -> Resource:
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    if resource.event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
        raise HTTPException(409, "Event is cancelled or completed")
    return resource


@router.post("/resources/{resource_id}/join", response_model=QueueJoinResult, status_code=201)
def join(resource_id: int, payload: QueueJoinRequest, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    resource = _load_resource(db, resource_id)
    fraud.check_rapid_joining(db, user.id)
    try:
        membership, right = queue_engine.join_queue(
            db, user.id, resource, invite_code=payload.invite_code, priority=user.priority_tier)
    except queue_engine.QueueEngineError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    db.commit()
    return QueueJoinResult(
        queue_id=membership.queue_id,
        membership_id=membership.id,
        position=right.position if right else
        queue_engine.predicted_position(db, membership.queue_id),
        access_right=AccessRightOut.model_validate(right) if right else None,
        message="Joined" if right else "Joined — position pending draw",
    )


@router.post("/resources/{resource_id}/leave", status_code=204)
def leave(resource_id: int, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)):
    resource = _load_resource(db, resource_id)
    try:
        queue_engine.leave_queue(db, user.id, resource)
    except queue_engine.QueueEngineError as e:
        raise HTTPException(e.status_code, detail={"code": e.code, "message": e.message})
    fraud.check_frequent_cancellations(db, user.id)
    db.commit()


@router.get("/resources/{resource_id}")
def queue_state(resource_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    resource = _load_resource(db, resource_id)
    queue = queue_engine.ensure_queue(db, resource)
    my_membership = db.scalar(select(QueueMembership).where(
        QueueMembership.queue_id == queue.id,
        QueueMembership.user_id == user.id,
        QueueMembership.active.is_(True)))
    from app.models import AccessRight
    right = db.scalar(select(AccessRight).where(
        AccessRight.queue_id == queue.id,
        AccessRight.owner_user_id == user.id,
        AccessRight.status.notin_(["CANCELLED", "TRANSFERRED"])))
    return {
        "queue_id": queue.id,
        "policy": queue.policy.value,
        "is_open": queue.is_open,
        "is_member": my_membership is not None,
        "my_position": right.position if right else None,
        "my_access_right": AccessRightOut.model_validate(right) if right else None,
        "predicted_position": queue_engine.predicted_position(db, queue.id),
    }


@router.post("/{queue_id}/draw")
def draw(queue_id: int, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    queue = db.get(Queue, queue_id)
    if not queue:
        raise HTTPException(404, "Queue not found")
    resource = queue.resource
    if not (resource.event.organizer and resource.event.organizer.user_id == user.id) \
            and user.role.value != "ADMIN":
        raise HTTPException(403, "Only the organizer can draw positions")
    count = queue_engine.draw(db, queue)
    db.commit()
    return {"assigned": count}
