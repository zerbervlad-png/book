"""Security primitives: password hashing (PBKDF2), JWT tokens, API keys.

Sections 60 (authentication, token rotation), 12 (digital tokens).
No third-party password libs: PBKDF2-HMAC-SHA256 with per-user salt.
"""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings

_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt, digest = encoded.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.ACCESS_TOKEN_TTL_SECONDS)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except jwt.InvalidTokenError:
        return None


def generate_token_code(prefix: str) -> str:
    """Human-readable unique digital token, e.g. AT-938283 (section 12)."""
    return f"{prefix}-{secrets.randbelow(10**9):09d}"
