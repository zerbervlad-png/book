"""Application configuration (section 60: security, token rotation)."""
import os


class Settings:
    APP_NAME: str = "Universal Access & Reservation Marketplace"
    API_PREFIX: str = "/api"
    DATABASE_URL: str = os.environ.get("AM_DATABASE_URL", "sqlite:///./access_marketplace.db")
    # A random per-process secret invalidates all tokens on restart and breaks
    # multi-worker deployments — use a stable dev default and require an
    # explicit AM_JWT_SECRET in production.
    JWT_SECRET: str = os.environ.get("AM_JWT_SECRET") or "dev-insecure-jwt-secret-change-me"
    ADMIN_EMAIL: str = os.environ.get("AM_ADMIN_EMAIL", "admin@access.marketplace")
    ADMIN_PASSWORD: str = os.environ.get("AM_ADMIN_PASSWORD", "ChangeMe-Admin-2026!")
    # Comma-separated list of allowed CORS origins; "*" disables credentials
    CORS_ORIGINS: str = os.environ.get("AM_CORS_ORIGINS", "*")
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
