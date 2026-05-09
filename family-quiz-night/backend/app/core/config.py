"""
Application configuration — loaded from environment variables.

All secrets come from env vars. Defaults are dev-safe.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Immutable, env-driven application settings."""

    # ── App ──
    app_name: str = "Family Quiz Night"
    debug: bool = False
    api_version: str = "v1"
    secret_key: str = "change-me-in-production"

    # ── Database ──
    database_url: str = "postgresql+asyncpg://quiz:quiz@localhost:5432/quiznight"
    db_echo: bool = False

    # ── Auth ──
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 10080  # 7 days

    # ── Premium / IAP ──
    premium_price_id: str = ""  # Stripe price ID or App Store product ID
    apple_shared_secret: str = ""
    google_play_key_path: str = ""

    # ── Rate limiting ──
    answer_reveal_rate_limit: int = 60   # max reveals per minute per user
    global_rate_limit: int = 200         # max requests per minute per IP

    # ── Pipeline integration ──
    anthropic_api_key: str = ""
    omdb_api_key: str = ""

    # ── Round assembly ──
    questions_per_round: int = 20
    min_quality_score: float = 0.5

    model_config = {"env_prefix": "QUIZ_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
