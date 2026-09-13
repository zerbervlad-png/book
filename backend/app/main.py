"""Application factory — sections 60, 61.

Middleware: JWT-free rate limiting per IP. All state-changing business logic
lives in engines; routers are thin. The backend is the single source of truth.
"""
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api import (
    access, analytics, auth, checkins, disputes, events, marketplace, notifications,
    organizers, payments, queues, reservations, resources, transfers, waitlists,
)
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.security import hash_password
from app.models import User, UserRole

app = FastAPI(title=settings.APP_NAME, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- rate limiting (60) ----------
RATE_BUCKETS: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client = request.client.host if request.client else "anon"
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        now = time.monotonic()
        bucket = RATE_BUCKETS[client]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= settings.RATE_LIMIT_PER_MINUTE:
            return JSONResponse(
                status_code=429,
                content={"detail": {"code": "RATE_LIMITED", "message": "Too many requests"}},
            )
        bucket.append(now)
    return await call_next(request)


# ---------- consistent error envelope ----------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, str):
        detail = {"code": "ERROR", "message": detail}
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "detail": {"code": "VALIDATION_ERROR", "message": exc.errors()[:5]}})


PREFIX = settings.API_PREFIX
for router in (auth.router, organizers.router, events.router, resources.router,
               queues.router, waitlists.router, access.router, reservations.router,
               transfers.router, payments.router, checkins.router, disputes.router,
               marketplace.router, notifications.router, analytics.router):
    app.include_router(router, prefix=PREFIX)


@app.on_event("startup")
def startup() -> None:
    init_db()
    # Bootstrap admin account if none exists (change the password in production!)
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.role == UserRole.ADMIN)):
            db.add(User(
                email="admin@access.marketplace",
                name="Platform Admin",
                password_hash=hash_password("ChangeMe-Admin-2026!"),
                role=UserRole.ADMIN,
            ))
            db.commit()


@app.get("/health")
def health():
    return {"status": "ok"}
