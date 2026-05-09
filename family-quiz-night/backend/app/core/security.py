"""
Security utilities — JWT tokens, password hashing, device auth.

Supports two auth modes:
  1. Anonymous device tokens (free tier) — no signup required
  2. Email/password accounts (premium upgrade path)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def create_access_token(
    subject: str,
    *,
    is_device: bool = False,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT.

    Args:
        subject:    User ID or device ID.
        is_device:  True for anonymous device tokens.
        expires_delta: Custom expiry (defaults to config).
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.jwt_expiry_minutes)
    )
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "dev": is_device,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT. Raises jwt.PyJWTError on failure."""
    settings = get_settings()
    return jwt.decode(
        token, settings.secret_key, algorithms=[settings.jwt_algorithm]
    )
