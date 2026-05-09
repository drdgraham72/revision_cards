"""
Quiz endpoints — the main API surface for the frontend.

Key anti-scrape measure: answers are served one at a time via
POST /rounds/{id}/reveal, never in bulk.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import User
from app.middleware.auth import get_current_user
from app.middleware.rate_limit import answer_limiter, get_client_ip
from app.schemas.api import (
    TopicListResponse,
    TopicSummary,
    RoundListResponse,
    RoundDetail,
    AnswerRevealRequest,
    AnswerRevealResponse,
    RoundCompleteRequest,
    RatingRequest,
    RatingResponse,
    ReportRequest,
    ReportResponse,
    UserStatsResponse,
)
from app.services.quiz_service import QuizService

router = APIRouter(prefix="/quiz", tags=["quiz"])


# ── Topics ──────────────────────────────────────────────────

@router.get("/topics", response_model=TopicListResponse)
async def list_topics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all topics with round counts and user completion."""
    svc = QuizService(db)
    topics = await svc.get_topics(user.id)
    return TopicListResponse(
        topics=[TopicSummary(**t) for t in topics],
    )


# ── Rounds ──────────────────────────────────────────────────

@router.get("/topics/{topic}/rounds", response_model=RoundListResponse)
async def list_rounds(
    topic: str,
    sort: str = "default",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get published rounds for a topic. Sort: default, rating, unseen, newest."""
    svc = QuizService(db)
    rounds = await svc.get_rounds(topic, user.id, sort)
    return RoundListResponse(rounds=rounds, total=len(rounds))


@router.get("/rounds/{round_id}", response_model=RoundDetail)
async def get_round(
    round_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get round detail with questions (NO answers)."""
    svc = QuizService(db)
    detail = await svc.get_round_detail(round_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Round not found")
    return detail


# ── Answer reveal (rate-limited, anti-scrape) ───────────────

@router.post("/rounds/{round_id}/reveal", response_model=AnswerRevealResponse)
async def reveal_answer(
    round_id: UUID,
    body: AnswerRevealRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Reveal a single answer. Rate-limited to prevent bulk scraping.

    The client sends one question_id at a time, and we return its answer.
    Progress is tracked server-side.
    """
    # Rate limit by user ID
    answer_limiter.check(str(user.id))

    svc = QuizService(db)
    result = await svc.reveal_answer(body.question_id, round_id, user.id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found in this round",
        )
    return result


# ── Ratings ─────────────────────────────────────────────────

@router.post("/rounds/{round_id}/rate", response_model=RatingResponse)
async def rate_round(
    round_id: UUID,
    body: RatingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit or update a star rating (1-5) for a round."""
    svc = QuizService(db)
    return await svc.rate_round(round_id, user.id, body.stars)


# ── Reports ─────────────────────────────────────────────────

@router.post("/questions/{question_id}/report", response_model=ReportResponse)
async def report_question(
    question_id: UUID,
    body: ReportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Flag a question as wrong, unclear, or offensive."""
    svc = QuizService(db)
    return await svc.report_question(question_id, user.id, body.reason, body.detail)


# ── User stats ──────────────────────────────────────────────

@router.get("/me/stats", response_model=UserStatsResponse)
async def get_my_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's quiz stats."""
    svc = QuizService(db)
    return await svc.get_user_stats(user.id)
