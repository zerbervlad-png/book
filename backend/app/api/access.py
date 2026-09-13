"""Access rights API — sections 9, 12, 22, 78.

The client receives policies and tokens; tokens are generated and validated
server-side only.
"""
import io

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.engines.checkin import _one_time_code
from app.models import AccessRight, User
from app.schemas import AccessRightOut

router = APIRouter(prefix="/access", tags=["access"])


@router.get("/my", response_model=list[AccessRightOut])
def my_rights(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rights = db.scalars(select(AccessRight).where(
        AccessRight.owner_user_id == user.id,
        AccessRight.status.notin_(["TRANSFERRED"]),
    ).order_by(AccessRight.created_at.desc())).all()
    return rights


@router.get("/{access_right_id}", response_model=AccessRightOut)
def get_right(access_right_id: int, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    right = db.get(AccessRight, access_right_id)
    if not right:
        raise HTTPException(404, "Access right not found")
    if right.owner_user_id != user.id and user.role.value != "ADMIN":
        raise HTTPException(403, "Not the owner")
    return right


@router.get("/{access_right_id}/qr")
def right_qr(access_right_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """Real QR PNG carrying the one-time code (sections 11, 12)."""
    right = db.get(AccessRight, access_right_id)
    if not right:
        raise HTTPException(404, "Access right not found")
    if right.owner_user_id != user.id:
        raise HTTPException(403, "Not the owner")
    payload = f"{right.token_code}:{_one_time_code(right.one_time_secret)}"
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/{access_right_id}/code")
def right_code(access_right_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    right = db.get(AccessRight, access_right_id)
    if not right:
        raise HTTPException(404, "Access right not found")
    if right.owner_user_id != user.id:
        raise HTTPException(403, "Not the owner")
    return {
        "token_code": right.token_code,
        "one_time_code": _one_time_code(right.one_time_secret),
        "kind": right.kind.value,
        "position": right.position,
        "expires_at": right.expires_at,
    }
