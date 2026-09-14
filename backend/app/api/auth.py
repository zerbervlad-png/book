"""Auth + users API."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.engines import fraud
from app.engines.audit import audit
from app.models import AuditEventType, User, UserRole
from app.schemas import TokenOut, UserCreate, UserLogin, UserOut

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=TokenOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(409, "Email already registered")
    fraud.check_registration_burst(db, payload.email.split("@")[-1])
    user = User(
        email=payload.email,
        name=payload.name or payload.email.split("@")[0],
        password_hash=hash_password(payload.password),
        role=UserRole.USER,
    )
    db.add(user)
    db.flush()
    audit(db, AuditEventType.USER_REGISTERED, "User", user.id, actor_user_id=user.id)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, user.role.value), user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=TokenOut)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    fraud.check_user_active(db, user)
    return TokenOut(access_token=create_access_token(user.id, user.role.value), user=UserOut.model_validate(user))


@router.get("/users/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    # users' emails must not be enumerable by arbitrary clients
    if user.id != user_id and user.role.value != "ADMIN":
        raise HTTPException(403, "You can only view your own profile")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    return target
