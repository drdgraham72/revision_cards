"""
Auth service — handles anonymous device auth and email account upgrades.

Two paths:
  1. Device auth: client sends a device UUID, gets a JWT. No signup.
     This is the default for free-tier users.
  2. Email auth: user creates an account (premium upgrade path).
     Migrates progress from device token to email account.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.db.models import User
from app.schemas.api import TokenResponse


class AuthService:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def device_login(self, device_id: str) -> TokenResponse:
        """
        Authenticate by device ID. Creates user if first time.

        No password, no email — just a stable device identifier.
        """
        stmt = select(User).where(User.device_id == device_id)
        result = await self._db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            user = User(device_id=device_id)
            self._db.add(user)
            await self._db.flush()

        token = create_access_token(str(user.id), is_device=True)
        return TokenResponse(
            access_token=token,
            user_id=user.id,
            is_premium=user.is_premium,
        )

    async def email_register(self, email: str, password: str) -> TokenResponse:
        """Create an email account. Raises ValueError if email exists."""
        stmt = select(User).where(User.email == email)
        result = await self._db.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError("Email already registered")

        user = User(
            email=email,
            password_hash=hash_password(password),
        )
        self._db.add(user)
        await self._db.flush()

        token = create_access_token(str(user.id))
        return TokenResponse(
            access_token=token,
            user_id=user.id,
            is_premium=user.is_premium,
        )

    async def email_login(self, email: str, password: str) -> TokenResponse:
        """Authenticate with email/password. Raises ValueError on failure."""
        stmt = select(User).where(User.email == email)
        result = await self._db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not user.password_hash:
            raise ValueError("Invalid credentials")
        if not verify_password(password, user.password_hash):
            raise ValueError("Invalid credentials")

        token = create_access_token(str(user.id))
        return TokenResponse(
            access_token=token,
            user_id=user.id,
            is_premium=user.is_premium,
        )

    async def link_device_to_email(
        self, device_user_id: UUID, email: str, password: str
    ) -> TokenResponse:
        """
        Upgrade a device user to an email account.
        Preserves all progress and ratings.
        """
        stmt = select(User).where(User.id == device_user_id)
        result = await self._db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("User not found")

        # Check email isn't taken
        email_check = select(User).where(User.email == email)
        if (await self._db.execute(email_check)).scalar_one_or_none():
            raise ValueError("Email already registered")

        user.email = email
        user.password_hash = hash_password(password)
        await self._db.flush()

        token = create_access_token(str(user.id))
        return TokenResponse(
            access_token=token,
            user_id=user.id,
            is_premium=user.is_premium,
        )
