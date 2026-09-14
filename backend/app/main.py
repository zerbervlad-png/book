"""Application factory — sections 60, 61.

Middleware: JWT-free rate limiting per IP. All state-changing business logic
lives in engines; routers are thin. The backend is the single source of truth.
"""
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

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

_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # credentials cannot be combined with the wildcard origin "*" (CORS spec)
    allow_credentials="*" not in _origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- rate limiting (60) ----------
RATE_BUCKETS: dict[str, deque] = defaultdict(deque)
RATE_BUCKET_LIMIT = 10_000


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client = request.client.host if request.client else "anon"
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        # evict idle buckets so the map cannot grow without bound
        if len(RATE_BUCKETS) > RATE_BUCKET_LIMIT:
            now = time.monotonic()
            for ip in [ip for ip, b in RATE_BUCKETS.items() if not b or now - b[-1] > 60]:
                RATE_BUCKETS.pop(ip, None)
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
    def _safe(e: dict) -> dict:
        ctx = e.get("ctx")
        if ctx is not None:
            e = dict(e)
            e["ctx"] = {k: str(v) for k, v in ctx.items()}
        return e
    return JSONResponse(status_code=422, content={
        "detail": {"code": "VALIDATION_ERROR", "message": [_safe(e) for e in exc.errors()[:5]]}})


PREFIX = settings.API_PREFIX
for router in (auth.router, organizers.router, events.router, resources.router,
               queues.router, waitlists.router, access.router, reservations.router,
               transfers.router, payments.router, checkins.router, disputes.router,
               marketplace.router, notifications.router, analytics.router):
    app.include_router(router, prefix=PREFIX)


def _bootstrap_admin() -> None:
    # Bootstrap admin account if none exists. Credentials come from the
    # AM_ADMIN_EMAIL / AM_ADMIN_PASSWORD env vars — always override the
    # insecure development defaults in production.
    import logging
    if settings.ADMIN_PASSWORD == "ChangeMe-Admin-2026!":
        logging.getLogger(__name__).warning(
            "Admin account uses the default development password — "
            "set AM_ADMIN_PASSWORD before deploying.")
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.role == UserRole.ADMIN)):
            db.add(User(
                email=settings.ADMIN_EMAIL,
                name="Platform Admin",
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                role=UserRole.ADMIN,
            ))
            db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _bootstrap_admin()
    yield


app.router.lifespan_context = lifespan


@app.get("/health")
def health():
    return {"status": "ok"}
