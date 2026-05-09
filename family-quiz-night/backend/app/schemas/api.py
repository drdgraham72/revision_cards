"""
Pydantic schemas — request/response models for the API.

These are the contracts between the backend and the frontend.
Answers are intentionally separated from questions so the client
can't scrape them in a single request.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════

class DeviceAuthRequest(BaseModel):
    """Anonymous device registration — no signup required."""
    device_id: str = Field(..., min_length=8, max_length=128)


class EmailAuthRequest(BaseModel):
    """Email/password login or registration."""
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    is_premium: bool


# ═══════════════════════════════════════════════════════════
# TOPICS
# ═══════════════════════════════════════════════════════════

class TopicSummary(BaseModel):
    id: str
    name: str
    icon: str
    color: str
    total_rounds: int
    completed_rounds: int


class TopicListResponse(BaseModel):
    topics: list[TopicSummary]


# ═══════════════════════════════════════════════════════════
# ROUNDS
# ═══════════════════════════════════════════════════════════

class RoundSummary(BaseModel):
    id: UUID
    title: str
    description: str | None
    topic: str
    question_count: int
    avg_rating: float
    rating_count: int
    times_played: int
    is_completed: bool = False
    user_rating: int | None = None
    published_at: datetime | None


class RoundListResponse(BaseModel):
    rounds: list[RoundSummary]
    total: int


class RoundDetail(BaseModel):
    """Full round with questions (but NOT answers)."""
    id: UUID
    title: str
    description: str | None
    topic: str
    questions: list[QuestionStub]


class QuestionStub(BaseModel):
    """Question without the answer — served in round detail."""
    id: UUID
    question_text: str
    difficulty: str
    position: int
    tags: list[str] = []


# Fix forward reference
RoundDetail.model_rebuild()


# ═══════════════════════════════════════════════════════════
# ANSWERS — served individually on reveal (anti-scrape)
# ═══════════════════════════════════════════════════════════

class AnswerRevealRequest(BaseModel):
    question_id: UUID
    round_id: UUID


class AnswerRevealResponse(BaseModel):
    question_id: UUID
    answer_text: str


# ═══════════════════════════════════════════════════════════
# USER ENGAGEMENT
# ═══════════════════════════════════════════════════════════

class RoundCompleteRequest(BaseModel):
    round_id: UUID


class RatingRequest(BaseModel):
    round_id: UUID
    stars: int = Field(..., ge=1, le=5)


class RatingResponse(BaseModel):
    round_id: UUID
    stars: int
    new_avg_rating: float


class ReportRequest(BaseModel):
    question_id: UUID
    reason: str = Field(..., pattern="^(wrong_answer|unclear|offensive|other)$")
    detail: str | None = Field(None, max_length=500)


class ReportResponse(BaseModel):
    report_id: UUID
    message: str = "Thanks for the report — we'll review it."


# ═══════════════════════════════════════════════════════════
# USER PROFILE / STATS
# ═══════════════════════════════════════════════════════════

class UserStatsResponse(BaseModel):
    rounds_completed: int
    questions_revealed: int
    average_rating_given: float | None
    favourite_topic: str | None
    is_premium: bool
