from fastapi import APIRouter

from .auth import router as auth_router
from .quiz import router as quiz_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(quiz_router)
