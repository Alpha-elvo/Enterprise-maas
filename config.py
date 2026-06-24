"""
config.py — Centralized Configuration Management
================================================
Single source of truth for all environment variables and runtime constants.
All modules import from here; nothing reads os.environ directly.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root (safe no-op if file absent)
load_dotenv(Path(__file__).parent / ".env")


class _Config:
    """
    Validated configuration container.
    Raises descriptive errors at import time if critical vars are missing,
    so the failure happens at startup rather than mid-execution.
    """

    # ── API ───────────────────────────────────────────────────────────────────
    GROQ_API_KEY: str       = os.getenv("GROQ_API_KEY", "")
    MODEL_ID: str           = os.getenv("MODEL_ID", "llama-3.1-8b-instant")
    GROQ_ENDPOINT: str      = "https://api.groq.com/openai/v1/chat/completions"

    # ── Reliability ───────────────────────────────────────────────────────────
    RATE_LIMIT_SLEEP: float = float(os.getenv("RATE_LIMIT_SLEEP", "4.0"))
    MAX_RETRIES: int        = int(os.getenv("MAX_RETRIES", "3"))
    REQUEST_TIMEOUT: int    = int(os.getenv("REQUEST_TIMEOUT", "30"))

    # ── Circuit Breaker ───────────────────────────────────────────────────────
    CB_FAILURE_THRESHOLD: int    = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
    CB_RECOVERY_TIMEOUT: int     = int(os.getenv("CB_RECOVERY_TIMEOUT", "60"))

    # ── Model Behaviour ───────────────────────────────────────────────────────
    MAX_TOKENS: int         = int(os.getenv("MAX_TOKENS", "1024"))
    TEMPERATURE: float      = float(os.getenv("TEMPERATURE", "0.3"))

    # ── Agent Thresholds ──────────────────────────────────────────────────────
    HIGH_IMPACT_THRESHOLD: int   = int(os.getenv("HIGH_IMPACT_THRESHOLD", "7"))
    CONFIDENCE_MINIMUM: float    = float(os.getenv("CONFIDENCE_MINIMUM", "0.6"))

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str         = os.getenv("SECRET_KEY", "change-me-in-production")
    ADMIN_PASSWORD: str     = os.getenv("ADMIN_PASSWORD", "admin123")
    ENABLE_AUTH: bool       = os.getenv("ENABLE_AUTH", "false").lower() == "true"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str       = os.getenv(
        "DATABASE_URL", "sqlite:///storage/enterprise_maas.db"
    )

    # ── Cache ─────────────────────────────────────────────────────────────────
    CACHE_TTL: int          = int(os.getenv("CACHE_TTL", "3600"))
    CACHE_MAX_SIZE: int     = int(os.getenv("CACHE_MAX_SIZE", "100"))

    # ── Email ─────────────────────────────────────────────────────────────────
    SMTP_HOST: str          = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int          = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str          = os.getenv("SMTP_USER", "")
    SMTP_PASS: str          = os.getenv("SMTP_PASS", "")
    ALERT_RECIPIENTS: list  = [
        r.strip()
        for r in os.getenv("ALERT_RECIPIENTS", "").split(",")
        if r.strip()
    ]

    # ── Multi-Tenancy ─────────────────────────────────────────────────────────
    DEFAULT_TENANT: str     = os.getenv("DEFAULT_TENANT", "default")

    # ── Paths ─────────────────────────────────────────────────────────────────
    BASE_DIR: Path          = Path(__file__).parent
    STORAGE_DIR: Path       = BASE_DIR / "storage"
    REPORTS_DIR: Path       = BASE_DIR / "reports"
    LOGS_DIR: Path          = BASE_DIR / "logs"

    # ── UI ────────────────────────────────────────────────────────────────────
    APP_TITLE: str          = "Enterprise Decision Intelligence Platform"
    APP_VERSION: str        = "2.0.0"
    APP_ICON: str           = "🧠"

    def bootstrap(self) -> None:
        """Create required directories and validate critical settings."""
        for d in [self.STORAGE_DIR, self.REPORTS_DIR, self.LOGS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        """Return list of validation error strings (empty = all good)."""
        errors: list[str] = []
        if not self.GROQ_API_KEY:
            errors.append(
                "GROQ_API_KEY is not set. "
                "Add it to .env or set as environment variable."
            )
        if self.SECRET_KEY == "change-me-in-production":
            errors.append(
                "SECRET_KEY is still the default placeholder. "
                "Set a long random string for production."
            )
        return errors

    def is_api_configured(self) -> bool:
        return bool(self.GROQ_API_KEY and self.GROQ_API_KEY != "your_groq_api_key_here")


# Module-level singleton — import this everywhere
config = _Config()
config.bootstrap()
