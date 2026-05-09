"""
Pipeline configuration — centralised settings.

In production, load from env vars or a config file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from models.domain import Topic


@dataclass
class PipelineConfig:
    """All tunables in one place."""

    # API keys
    omdb_api_key: str = ""
    anthropic_api_key: str = ""

    # Stage 1 — Trawler
    scrape_limit_per_source: int = 50
    topics_to_scrape: list[Topic] = field(
        default_factory=lambda: list(Topic)
    )

    # Stage 2 — Generator
    # (no config needed — templates are self-contained)

    # Stage 3 — Quality Gate
    quality_model: str = "claude-sonnet-4-20250514"
    min_approval_score: float = 0.5

    # Storage
    data_dir: Path = Path("./data")

    @property
    def factoid_store_path(self) -> Path:
        return self.data_dir / "factoids.jsonl"

    @property
    def question_store_path(self) -> Path:
        return self.data_dir / "questions.jsonl"
