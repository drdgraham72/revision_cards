"""
Auth endpoints — device login, email register/login, account linking.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import User
from app.middleware.auth import get_current_user
from app.schemas.api import (
    DeviceAuthRequest,
    EmailAuthRequest,
    TokenResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/device", response_model=TokenResponse)
async def device_login(
    body: DeviceAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Anonymous device login. Creates user on first call.
    No signup required — just send a stable device ID.
    """
    svc = AuthService(db)
    return await svc.device_login(body.device_id)


@router.post("/register", response_model=TokenResponse)
async def email_register(
    body: EmailAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create an email account."""
    svc = AuthService(db)
    try:
        return await svc.email_register(body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/login", response_model=TokenResponse)
async def email_login(
    body: EmailAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """Login with email and password."""
    svc = AuthService(db)
    try:
        return await svc.email_login(body.email, body.password)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )


@router.post("/link", response_model=TokenResponse)
async def link_device_to_email(
    body: EmailAuthRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upgrade a device user to an email account. Preserves all progress."""
    svc = AuthService(db)
    try:
        return await svc.link_device_to_email(user.id, body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
