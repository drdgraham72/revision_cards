"""
Database models — the complete schema for Family Quiz Night.

Tables:
  users             — both anonymous device users and email accounts
  questions         — approved questions from the pipeline
  rounds            — assembled rounds of N questions
  round_questions   — M2M: which questions belong to which round
  user_progress     — tracks which rounds a user has completed
  user_ratings      — star ratings per round
  question_reports  — user-flagged bad questions
  factoids          — raw trawled data (pipeline Stage 1 output)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Shared base for all ORM models."""
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ═══════════════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    device_id = Column(String(128), unique=True, nullable=True, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    display_name = Column(String(100), nullable=True)
    is_premium = Column(Boolean, default=False, nullable=False)
    premium_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_active_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Relationships
    progress = relationship("UserProgress", back_populates="user", lazy="selectin")
    ratings = relationship("UserRating", back_populates="user", lazy="selectin")
    reports = relationship("QuestionReport", back_populates="user", lazy="selectin")


# ═══════════════════════════════════════════════════════════
# CONTENT — questions, rounds, and their relationships
# ═══════════════════════════════════════════════════════════

class Question(Base):
    __tablename__ = "questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False)
    topic = Column(String(32), nullable=False, index=True)
    difficulty = Column(String(16), nullable=False)
    quality_score = Column(Float, default=0.0, nullable=False)
    tags = Column(ARRAY(String), default=list, nullable=False)
    source_entity = Column(String(128), nullable=True)
    template_id = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    report_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_questions_topic_score", "topic", "quality_score"),
        Index("ix_questions_active_topic", "is_active", "topic"),
    )


class Round(Base):
    __tablename__ = "rounds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    topic = Column(String(32), nullable=False, index=True)
    difficulty_mix = Column(String(16), default="mixed", nullable=False)
    question_count = Column(Integer, nullable=False)
    avg_quality_score = Column(Float, default=0.0, nullable=False)
    avg_user_rating = Column(Float, default=0.0, nullable=False)
    rating_count = Column(Integer, default=0, nullable=False)
    times_played = Column(Integer, default=0, nullable=False)
    is_published = Column(Boolean, default=False, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Relationships
    round_questions = relationship(
        "RoundQuestion", back_populates="round", lazy="selectin",
        order_by="RoundQuestion.position",
    )

    __table_args__ = (
        Index("ix_rounds_topic_published", "topic", "is_published"),
        Index("ix_rounds_avg_rating", "avg_user_rating"),
    )


class RoundQuestion(Base):
    """Join table — positions questions within a round."""
    __tablename__ = "round_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    round_id = Column(
        UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    question_id = Column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    position = Column(Integer, nullable=False)

    round = relationship("Round", back_populates="round_questions")
    question = relationship("Question", lazy="joined")

    __table_args__ = (
        UniqueConstraint("round_id", "question_id", name="uq_round_question"),
        UniqueConstraint("round_id", "position", name="uq_round_position"),
    )


# ═══════════════════════════════════════════════════════════
# USER ENGAGEMENT — progress, ratings, reports
# ═══════════════════════════════════════════════════════════

class UserProgress(Base):
    """Tracks which rounds a user has completed."""
    __tablename__ = "user_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_id = Column(
        UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    questions_revealed = Column(Integer, default=0, nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="progress")

    __table_args__ = (
        UniqueConstraint("user_id", "round_id", name="uq_user_round_progress"),
        Index("ix_progress_user_completed", "user_id", "is_completed"),
    )


class UserRating(Base):
    """Star ratings (1-5) per round per user."""
    __tablename__ = "user_ratings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_id = Column(
        UUID(as_uuid=True), ForeignKey("rounds.id", ondelete="CASCADE"),
        nullable=False,
    )
    stars = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("user_id", "round_id", name="uq_user_round_rating"),
    )


class QuestionReport(Base):
    """User-flagged bad questions — feeds human review queue."""
    __tablename__ = "question_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id = Column(
        UUID(as_uuid=True), ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason = Column(String(32), nullable=False)  # wrong_answer, unclear, offensive, other
    detail = Column(Text, nullable=True)
    is_reviewed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="reports")

    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_user_question_report"),
    )


# ═══════════════════════════════════════════════════════════
# PIPELINE — factoids stored for reprocessing
# ═══════════════════════════════════════════════════════════

class Factoid(Base):
    __tablename__ = "factoids"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    entity_id = Column(String(128), nullable=False)
    topic = Column(String(32), nullable=False, index=True)
    entity_name = Column(String(300), nullable=False)
    source = Column(String(64), nullable=False)
    attributes = Column(JSONB, nullable=False, default=dict)
    scraped_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("entity_id", "source", name="uq_factoid_entity_source"),
        Index("ix_factoids_topic_source", "topic", "source"),
    )
