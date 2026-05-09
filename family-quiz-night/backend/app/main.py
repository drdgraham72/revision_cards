"""
Family Quiz Night — API server.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.core.config import get_settings
from app.db.session import engine
from app.db.models import Base
from app.middleware.rate_limit import global_limiter, get_client_ip


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup (dev only — use alembic in prod)."""
    settings = get_settings()
    if settings.debug:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="Family Quiz Night",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global rate limit ──
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = get_client_ip(request)
    try:
        global_limiter.check(ip)
    except Exception as exc:
        return JSONResponse(status_code=429, content={"detail": str(exc)})
    return await call_next(request)


# ── Routes ──
app.include_router(api_router)


# ── Health check ──
@app.get("/health")
async def health():
    return {"status": "ok", "service": "quiz-night-api"}
