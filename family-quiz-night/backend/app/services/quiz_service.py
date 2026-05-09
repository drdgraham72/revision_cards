"""
Quiz service — core business logic for serving quiz content.

Key design decisions:
  - Answers are never sent with the round listing. They're fetched
    one at a time via reveal_answer(). This prevents bulk scraping.
  - Rounds are assembled by the pipeline and stored as published
    entities. The API just serves them.
  - Progress is tracked server-side to prevent local tampering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Question,
    Round,
    RoundQuestion,
    UserProgress,
    UserRating,
    QuestionReport,
)
from app.schemas.api import (
    RoundSummary,
    RoundDetail,
    QuestionStub,
    AnswerRevealResponse,
    RatingResponse,
    ReportResponse,
    UserStatsResponse,
)

# Topic metadata — mirrors the frontend
TOPIC_META = {
    "movies":    {"name": "Movies",       "icon": "🎬", "color": "#e879f9"},
    "music":     {"name": "Music",        "icon": "🎵", "color": "#22d3ee"},
    "science":   {"name": "Science",      "icon": "🔬", "color": "#60a5fa"},
    "history":   {"name": "History",      "icon": "📜", "color": "#f59e0b"},
    "geography": {"name": "Geography",    "icon": "🌍", "color": "#34d399"},
    "sport":     {"name": "Sport",        "icon": "⚽", "color": "#fb923c"},
    "food":      {"name": "Food & Drink", "icon": "🍽️", "color": "#a78bfa"},
    "nature":    {"name": "Nature",       "icon": "🌿", "color": "#4ade80"},
}


class QuizService:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Topics ──────────────────────────────────────────────

    async def get_topics(self, user_id: UUID) -> list[dict]:
        """Get all topics with round counts and user completion."""
        topics = []
        for topic_id, meta in TOPIC_META.items():
            # Total published rounds
            total_stmt = select(func.count(Round.id)).where(
                Round.topic == topic_id, Round.is_published == True  # noqa: E712
            )
            total = (await self._db.execute(total_stmt)).scalar() or 0

            # User completed rounds
            completed_stmt = (
                select(func.count(UserProgress.id))
                .join(Round, Round.id == UserProgress.round_id)
                .where(
                    UserProgress.user_id == user_id,
                    UserProgress.is_completed == True,  # noqa: E712
                    Round.topic == topic_id,
                )
            )
            completed = (await self._db.execute(completed_stmt)).scalar() or 0

            topics.append({
                "id": topic_id,
                **meta,
                "total_rounds": total,
                "completed_rounds": completed,
            })

        return topics

    # ── Rounds ──────────────────────────────────────────────

    async def get_rounds(
        self,
        topic: str,
        user_id: UUID,
        sort: str = "default",
    ) -> list[RoundSummary]:
        """Get published rounds for a topic, with user state."""
        stmt = (
            select(Round)
            .where(Round.topic == topic, Round.is_published == True)  # noqa: E712
        )

        if sort == "rating":
            stmt = stmt.order_by(Round.avg_user_rating.desc())
        elif sort == "newest":
            stmt = stmt.order_by(Round.published_at.desc())
        else:
            stmt = stmt.order_by(Round.published_at.desc())

        result = await self._db.execute(stmt)
        rounds = result.scalars().all()

        summaries = []
        for r in rounds:
            # User progress for this round
            progress_stmt = select(UserProgress).where(
                UserProgress.user_id == user_id,
                UserProgress.round_id == r.id,
            )
            progress = (await self._db.execute(progress_stmt)).scalar_one_or_none()

            # User rating for this round
            rating_stmt = select(UserRating).where(
                UserRating.user_id == user_id,
                UserRating.round_id == r.id,
            )
            rating = (await self._db.execute(rating_stmt)).scalar_one_or_none()

            summaries.append(RoundSummary(
                id=r.id,
                title=r.title,
                description=r.description,
                topic=r.topic,
                question_count=r.question_count,
                avg_rating=r.avg_user_rating,
                rating_count=r.rating_count,
                times_played=r.times_played,
                is_completed=progress.is_completed if progress else False,
                user_rating=rating.stars if rating else None,
                published_at=r.published_at,
            ))

        # Sort unseen first if requested
        if sort == "unseen":
            summaries.sort(key=lambda s: (s.is_completed, s.published_at or datetime.min))

        return summaries

    # ── Round detail (no answers) ───────────────────────────

    async def get_round_detail(self, round_id: UUID) -> RoundDetail | None:
        """Get full round with question texts but NO answers."""
        stmt = select(Round).where(Round.id == round_id)
        result = await self._db.execute(stmt)
        rnd = result.scalar_one_or_none()
        if not rnd:
            return None

        # Get questions via join table
        q_stmt = (
            select(RoundQuestion, Question)
            .join(Question, Question.id == RoundQuestion.question_id)
            .where(RoundQuestion.round_id == round_id)
            .order_by(RoundQuestion.position)
        )
        q_result = await self._db.execute(q_stmt)
        rows = q_result.all()

        questions = [
            QuestionStub(
                id=q.id,
                question_text=q.question_text,
                difficulty=q.difficulty,
                position=rq.position,
                tags=q.tags or [],
            )
            for rq, q in rows
        ]

        return RoundDetail(
            id=rnd.id,
            title=rnd.title,
            description=rnd.description,
            topic=rnd.topic,
            questions=questions,
        )

    # ── Answer reveal (anti-scrape) ─────────────────────────

    async def reveal_answer(
        self, question_id: UUID, round_id: UUID, user_id: UUID
    ) -> AnswerRevealResponse | None:
        """
        Reveal a single answer. Tracks progress server-side.

        Returns None if question doesn't exist or isn't in this round.
        """
        # Verify question belongs to this round
        verify_stmt = select(RoundQuestion).where(
            RoundQuestion.round_id == round_id,
            RoundQuestion.question_id == question_id,
        )
        if not (await self._db.execute(verify_stmt)).scalar_one_or_none():
            return None

        # Get the answer
        q_stmt = select(Question).where(Question.id == question_id)
        question = (await self._db.execute(q_stmt)).scalar_one_or_none()
        if not question:
            return None

        # Update progress
        await self._update_progress(user_id, round_id)

        return AnswerRevealResponse(
            question_id=question.id,
            answer_text=question.answer_text,
        )

    async def _update_progress(self, user_id: UUID, round_id: UUID) -> None:
        """Increment reveal count, mark complete if all revealed."""
        stmt = select(UserProgress).where(
            UserProgress.user_id == user_id,
            UserProgress.round_id == round_id,
        )
        progress = (await self._db.execute(stmt)).scalar_one_or_none()

        if not progress:
            progress = UserProgress(
                user_id=user_id,
                round_id=round_id,
                questions_revealed=1,
            )
            self._db.add(progress)
        else:
            progress.questions_revealed += 1

        # Check if round is complete
        rnd_stmt = select(Round).where(Round.id == round_id)
        rnd = (await self._db.execute(rnd_stmt)).scalar_one_or_none()
        if rnd and progress.questions_revealed >= rnd.question_count:
            progress.is_completed = True
            progress.completed_at = datetime.now(timezone.utc)

            # Increment times_played on the round
            await self._db.execute(
                update(Round)
                .where(Round.id == round_id)
                .values(times_played=Round.times_played + 1)
            )

        await self._db.flush()

    # ── Ratings ─────────────────────────────────────────────

    async def rate_round(
        self, round_id: UUID, user_id: UUID, stars: int
    ) -> RatingResponse:
        """Submit or update a star rating for a round."""
        # Upsert rating
        stmt = select(UserRating).where(
            UserRating.user_id == user_id,
            UserRating.round_id == round_id,
        )
        existing = (await self._db.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.stars = stars
        else:
            self._db.add(UserRating(
                user_id=user_id, round_id=round_id, stars=stars,
            ))

        await self._db.flush()

        # Recalculate round average
        avg_stmt = select(func.avg(UserRating.stars)).where(
            UserRating.round_id == round_id
        )
        avg = (await self._db.execute(avg_stmt)).scalar() or 0

        count_stmt = select(func.count(UserRating.id)).where(
            UserRating.round_id == round_id
        )
        count = (await self._db.execute(count_stmt)).scalar() or 0

        await self._db.execute(
            update(Round)
            .where(Round.id == round_id)
            .values(avg_user_rating=round(avg, 2), rating_count=count)
        )

        return RatingResponse(
            round_id=round_id, stars=stars, new_avg_rating=round(avg, 2),
        )

    # ── Reports ─────────────────────────────────────────────

    async def report_question(
        self,
        question_id: UUID,
        user_id: UUID,
        reason: str,
        detail: str | None,
    ) -> ReportResponse:
        """Flag a question for review."""
        report = QuestionReport(
            user_id=user_id,
            question_id=question_id,
            reason=reason,
            detail=detail,
        )
        self._db.add(report)

        # Increment report count on question
        await self._db.execute(
            update(Question)
            .where(Question.id == question_id)
            .values(report_count=Question.report_count + 1)
        )

        # Auto-disable questions with too many reports
        q = (await self._db.execute(
            select(Question).where(Question.id == question_id)
        )).scalar_one_or_none()
        if q and q.report_count >= 5:
            q.is_active = False

        await self._db.flush()
        return ReportResponse(report_id=report.id)

    # ── User stats ──────────────────────────────────────────

    async def get_user_stats(self, user_id: UUID) -> UserStatsResponse:
        """Aggregate stats for a user's profile."""
        # Rounds completed
        completed_stmt = select(func.count(UserProgress.id)).where(
            UserProgress.user_id == user_id,
            UserProgress.is_completed == True,  # noqa: E712
        )
        rounds_done = (await self._db.execute(completed_stmt)).scalar() or 0

        # Total reveals
        reveals_stmt = select(func.sum(UserProgress.questions_revealed)).where(
            UserProgress.user_id == user_id,
        )
        reveals = (await self._db.execute(reveals_stmt)).scalar() or 0

        # Average rating given
        avg_rating_stmt = select(func.avg(UserRating.stars)).where(
            UserRating.user_id == user_id,
        )
        avg_rating = (await self._db.execute(avg_rating_stmt)).scalar()

        # Favourite topic (most completed rounds)
        fav_stmt = (
            select(Round.topic, func.count(UserProgress.id).label("cnt"))
            .join(Round, Round.id == UserProgress.round_id)
            .where(
                UserProgress.user_id == user_id,
                UserProgress.is_completed == True,  # noqa: E712
            )
            .group_by(Round.topic)
            .order_by(func.count(UserProgress.id).desc())
            .limit(1)
        )
        fav_result = (await self._db.execute(fav_stmt)).first()
        fav_topic = fav_result[0] if fav_result else None

        # Premium status
        from app.db.models import User
        user = (await self._db.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()

        return UserStatsResponse(
            rounds_completed=rounds_done,
            questions_revealed=reveals,
            average_rating_given=round(avg_rating, 2) if avg_rating else None,
            favourite_topic=fav_topic,
            is_premium=user.is_premium if user else False,
        )
