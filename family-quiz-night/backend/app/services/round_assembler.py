"""
Round assembly service — run as part of the nightly pipeline.

Takes approved questions from the DB and assembles them into
publishable rounds. Handles:
  - Grouping by topic
  - Mixing difficulties within a round
  - Avoiding duplicate questions across rounds
  - Generating round titles and descriptions
  - Publishing new rounds
"""

from __future__ import annotations

import random
import logging
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Question, Round, RoundQuestion
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Title templates per topic — rotated to avoid repetition
_TITLE_TEMPLATES: dict[str, list[str]] = {
    "movies":    ["Silver Screen Stumpers", "Director's Cut", "Plot Twist", "Reel Talk", "The Final Act", "Opening Night", "Hidden Gems", "Box Office Brain Teasers"],
    "music":     ["Studio Sessions", "Vinyl Deep Cuts", "Chart Toppers", "The Encore Round", "Backstage Pass", "Mixtape Memories", "Sound Check"],
    "science":   ["Lab Coat Required", "Mind Benders", "Particle Puzzlers", "Hypothesis Hour", "The Experiment", "Eureka Moments", "Quantum Questions"],
    "history":   ["Time Warp", "Plot Twists of History", "Ancient Mysteries", "History Repeats", "The Archives", "Turning Points", "Forgotten Stories"],
    "geography": ["Border Benders", "Atlas Challenge", "Globe Trotters", "Map Quest", "Uncharted Territory", "Meridian Madness", "Capital Gains"],
    "sport":     ["Off the Bench", "Sudden Death", "The Trophy Room", "Half Time Teasers", "Record Breakers", "Underdog Stories", "Championship Round"],
    "food":      ["Taste Test", "Kitchen Confidential", "The Secret Ingredient", "Fork in the Road", "Spice Rack", "Fermentation Station", "Chef's Table"],
    "nature":    ["Wild Cards", "Into the Wild", "Deep Blue", "Creature Feature", "Root & Branch", "Survival of the Fittest", "Natural Wonders"],
}


class RoundAssembler:

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._settings = get_settings()

    async def assemble_and_publish(self, topic: str) -> Round | None:
        """
        Assemble a new round for the given topic from unassigned questions.

        Returns the published Round, or None if not enough questions.
        """
        n = self._settings.questions_per_round

        # Find questions not yet in any round
        assigned_ids_stmt = select(RoundQuestion.question_id)
        assigned_ids = {
            row[0]
            for row in (await self._db.execute(assigned_ids_stmt)).all()
        }

        # Get eligible questions
        q_stmt = (
            select(Question)
            .where(
                Question.topic == topic,
                Question.is_active == True,  # noqa: E712
                Question.quality_score >= self._settings.min_quality_score,
            )
            .order_by(Question.quality_score.desc())
            .limit(n * 3)  # Over-fetch to allow filtering
        )
        result = await self._db.execute(q_stmt)
        candidates = [q for q in result.scalars().all() if q.id not in assigned_ids]

        if len(candidates) < n:
            logger.warning(
                "Not enough unassigned questions for '%s': %d/%d",
                topic, len(candidates), n,
            )
            return None

        # Mix difficulties: aim for 30% easy, 50% medium, 20% hard
        easy = [q for q in candidates if q.difficulty == "easy"]
        medium = [q for q in candidates if q.difficulty == "medium"]
        hard = [q for q in candidates if q.difficulty == "hard"]

        selected: list[Question] = []
        for pool, target in [(easy, int(n * 0.3)), (medium, int(n * 0.5)), (hard, int(n * 0.2))]:
            random.shuffle(pool)
            selected.extend(pool[:target])

        # Fill remainder from whatever's left
        remaining = [q for q in candidates if q not in selected]
        random.shuffle(remaining)
        selected.extend(remaining[: n - len(selected)])
        selected = selected[:n]

        # Shuffle final order
        random.shuffle(selected)

        # Pick a title
        title = await self._pick_title(topic)

        # Calculate avg quality
        avg_score = sum(q.quality_score for q in selected) / len(selected)

        # Create round
        rnd = Round(
            title=title,
            description=f"{len(selected)} questions across mixed difficulties",
            topic=topic,
            difficulty_mix="mixed",
            question_count=len(selected),
            avg_quality_score=round(avg_score, 3),
            is_published=True,
            published_at=datetime.now(timezone.utc),
        )
        self._db.add(rnd)
        await self._db.flush()

        # Create join records
        for pos, question in enumerate(selected):
            self._db.add(RoundQuestion(
                round_id=rnd.id,
                question_id=question.id,
                position=pos,
            ))

        await self._db.flush()
        logger.info(
            "Published round '%s' for '%s' with %d questions (avg score: %.3f)",
            title, topic, len(selected), avg_score,
        )
        return rnd

    async def _pick_title(self, topic: str) -> str:
        """Pick a title that hasn't been used recently."""
        templates = _TITLE_TEMPLATES.get(topic, ["Quiz Round"])

        # Check existing titles
        existing_stmt = select(Round.title).where(Round.topic == topic)
        existing = {
            row[0] for row in (await self._db.execute(existing_stmt)).all()
        }

        available = [t for t in templates if t not in existing]
        if not available:
            # All titles used — append a number
            count_stmt = select(func.count(Round.id)).where(Round.topic == topic)
            count = (await self._db.execute(count_stmt)).scalar() or 0
            return f"{random.choice(templates)} #{count + 1}"

        return random.choice(available)
