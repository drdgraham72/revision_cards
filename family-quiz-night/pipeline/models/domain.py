"""
Domain models for the quiz pipeline.

These are the shared contracts between all three stages:
  Stage 1 (Trawler)  → produces Factoid
  Stage 2 (Generator) → consumes Factoid, produces QuestionCandidate
  Stage 3 (QualityGate) → consumes QuestionCandidate, produces ApprovedQuestion
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Topic(str, Enum):
    """Top-level quiz topics — mirrors the frontend TOPICS array."""
    MOVIES = "movies"
    MUSIC = "music"
    SCIENCE = "science"
    HISTORY = "history"
    GEOGRAPHY = "geography"
    SPORT = "sport"
    FOOD = "food"
    NATURE = "nature"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass
class Factoid:
    """
    Stage 1 output — a structured blob of data about a single entity.

    The trawler scrapes raw data and normalises it into this shape.
    One Factoid per entity (e.g. one film, one album, one species).
    The `attributes` dict is schema-free per topic; the generator
    knows how to read each topic's attribute keys.

    Example (Movies):
        Factoid(
            entity_id="tt1375666",
            topic=Topic.MOVIES,
            entity_name="Inception",
            source="omdb",
            attributes={
                "year": 2010,
                "director": "Christopher Nolan",
                "cast": ["Leonardo DiCaprio", "Joseph Gordon-Levitt", ...],
                "genre": ["Action", "Sci-Fi", "Thriller"],
                "awards": "Won 4 Oscars. 157 wins & 220 nominations total",
                "plot": "A thief who steals corporate secrets through ...",
                "box_office": "$292,576,195",
                "runtime_min": 148,
                "imdb_rating": 8.8,
                "country": "USA, UK",
                "language": "English, Japanese, French",
                "notable_facts": [
                    "The hallway fight scene used a rotating set",
                    "Hans Zimmer's score uses a slowed-down Édith Piaf song",
                ]
            }
        )
    """
    entity_id: str
    topic: Topic
    entity_name: str
    source: str
    attributes: dict[str, Any]
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def has(self, *keys: str) -> bool:
        """Check if all attribute keys exist and are truthy."""
        return all(self.attributes.get(k) for k in keys)


@dataclass
class QuestionCandidate:
    """
    Stage 2 output — a generated question/answer pair with metadata.

    Produced by deterministic template logic from a Factoid.
    Not yet vetted for quality — that's Stage 3's job.
    """
    question: str
    answer: str
    topic: Topic
    difficulty: Difficulty
    source_factoid_id: str
    template_id: str
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    generated_at: datetime = field(default_factory=datetime.utcnow)


class QualityVerdict(str, Enum):
    """Stage 3 decisions."""
    APPROVED = "approved"
    REWRITE = "rewrite"       # AI suggests a rewrite
    REJECTED = "rejected"     # not fun / too obscure / factually shaky


@dataclass
class QualityResult:
    """Stage 3 output — the AI's assessment of a QuestionCandidate."""
    candidate_id: str
    verdict: QualityVerdict
    score: float              # 0.0–1.0 composite quality score
    clarity: float            # 0.0–1.0
    fun_factor: float         # 0.0–1.0
    difficulty_accurate: bool
    rewritten_question: str | None = None
    rewritten_answer: str | None = None
    reason: str = ""


@dataclass
class ApprovedQuestion:
    """
    Final output — ready to be served to the frontend.

    May contain the original or a rewritten version from Stage 3.
    """
    question: str
    answer: str
    topic: Topic
    difficulty: Difficulty
    score: float
    tags: list[str] = field(default_factory=list)
    source_entity: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
