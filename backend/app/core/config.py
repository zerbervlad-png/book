"""Application configuration (section 60: security, token rotation)."""
import os
import secrets


class Settings:
    APP_NAME: str = "Universal Access & Reservation Marketplace"
    API_PREFIX: str = "/api"
    DATABASE_URL: str = os.environ.get("AM_DATABASE_URL", "sqlite:///./access_marketplace.db")
    JWT_SECRET: str = os.environ.get("AM_JWT_SECRET", secrets.token_hex(32))
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_SECONDS: int = int(os.environ.get("AM_TOKEN_TTL", str(12 * 3600)))
    RESERVATION_TTL_SECONDS: int = int(os.environ.get("AM_RESERVATION_TTL", str(15 * 60)))
    WAITLIST_OFFER_TTL_SECONDS: int = int(os.environ.get("AM_WAITLIST_OFFER_TTL", str(30 * 60)))
    TRANSFER_TTL_SECONDS: int = int(os.environ.get("AM_TRANSFER_TTL", str(15 * 60)))
    DEFAULT_PLATFORM_FEE_PERCENT: float = float(os.environ.get("AM_PLATFORM_FEE", "5.0"))
    CURRENCY: str = "RUB"
    RATE_LIMIT_PER_MINUTE: int = int(os.environ.get("AM_RATE_LIMIT", "240"))
    IDEMPOTENCY_TTL_SECONDS: int = 24 * 3600


settings = Settings()
