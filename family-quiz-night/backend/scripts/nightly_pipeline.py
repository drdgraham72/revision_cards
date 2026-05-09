#!/usr/bin/env python3
"""
Nightly pipeline — run via cron to produce fresh quiz rounds.

Workflow:
  1. Trawl new factoids from external sources
  2. Generate question candidates (deterministic templates)
  3. Curate via AI quality gate (the only token spend)
  4. Insert approved questions into the DB
  5. Assemble and publish new rounds

Usage:
    # Full run — all topics
    python scripts/nightly_pipeline.py

    # Single topic
    python scripts/nightly_pipeline.py --topic movies

    # Dry run — skip AI gate, don't publish
    python scripts/nightly_pipeline.py --dry-run

Cron example (run at 3am daily):
    0 3 * * * cd /app && python scripts/nightly_pipeline.py >> /var/log/quiz-pipeline.log 2>&1
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import os
import sys
import uuid
from pathlib import Path

# Add project roots to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PIPELINE_ROOT = Path(__file__).resolve().parent.parent.parent / "quiz-pipeline"
if PIPELINE_ROOT.exists():
    sys.path.insert(0, str(PIPELINE_ROOT))

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.db.models import Base, Question, Factoid as DBFactoid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nightly")

# Pipeline imports (from quiz-pipeline project)
from models.domain import Topic, Factoid, QualityVerdict
from trawler import TrawlerOrchestrator
from trawler.sources import OMDBSource, WikipediaSource
from generator import QuestionEngine
from quality_gate import ClaudeQualityGate
from storage import JsonFactoidStore, JsonQuestionStore
from app.services.round_assembler import RoundAssembler


TOPIC_MAP = {t.value: t for t in Topic}


async def run(topics: list[str], dry_run: bool = False) -> None:
    settings = get_settings()

    # Ensure DB tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Temp storage for pipeline stages
    data_dir = Path("/tmp/quiz-pipeline-data")
    data_dir.mkdir(exist_ok=True)
    factoid_store = JsonFactoidStore(data_dir / "factoids.jsonl")

    # Stage 1: Trawl
    trawler = TrawlerOrchestrator(store=factoid_store)
    if settings.omdb_api_key:
        trawler.register(OMDBSource(api_key=settings.omdb_api_key))
    trawler.register(WikipediaSource())

    # Stage 2: Generate
    engine_gen = QuestionEngine()

    # Stage 3: Quality gate
    gate = None
    if settings.anthropic_api_key and not dry_run:
        gate = ClaudeQualityGate(
            api_key=settings.anthropic_api_key,
            model="claude-sonnet-4-20250514",
        )

    for topic_str in topics:
        topic = TOPIC_MAP.get(topic_str)
        if not topic:
            logger.warning("Unknown topic: %s", topic_str)
            continue

        logger.info("=" * 60)
        logger.info("PROCESSING: %s", topic.value.upper())
        logger.info("=" * 60)

        # Stage 1
        logger.info("[Stage 1] Trawling...")
        new_factoids = await trawler.run(topic, limit_per_source=50)
        all_factoids = await factoid_store.get_by_topic(topic, limit=200)
        logger.info("  → %d factoids (%d new)", len(all_factoids), len(new_factoids))

        if not all_factoids:
            logger.warning("  → No factoids, skipping")
            continue

        # Stage 2
        logger.info("[Stage 2] Generating candidates...")
        candidates = engine_gen.generate_batch(all_factoids)
        logger.info("  → %d candidates", len(candidates))

        if not candidates:
            continue

        # Stage 3
        if gate:
            logger.info("[Stage 3] AI quality gate...")
            results = await gate.evaluate(candidates)
            qr_map = {r.candidate_id: r for r in results}
        else:
            logger.info("[Stage 3] Skipped (dry run or no API key)")
            qr_map = None

        # Insert approved questions into DB
        async with SessionLocal() as db:
            inserted = 0
            for candidate in candidates:
                if qr_map:
                    qr = qr_map.get(candidate.id)
                    if not qr:
                        continue
                    if qr.verdict == QualityVerdict.REJECTED:
                        continue
                    if qr.score < settings.min_quality_score:
                        continue

                    q_text = qr.rewritten_question or candidate.question
                    a_text = qr.rewritten_answer or candidate.answer
                    score = qr.score
                else:
                    q_text = candidate.question
                    a_text = candidate.answer
                    score = 0.5  # Default for dry run

                question = Question(
                    question_text=q_text,
                    answer_text=a_text,
                    topic=candidate.topic.value,
                    difficulty=candidate.difficulty.value,
                    quality_score=score,
                    tags=candidate.tags,
                    source_entity=candidate.source_factoid_id,
                    template_id=candidate.template_id,
                )
                db.add(question)
                inserted += 1

            await db.commit()
            logger.info("  → Inserted %d questions into DB", inserted)

            # Stage 4: Assemble rounds
            if not dry_run:
                logger.info("[Stage 4] Assembling rounds...")
                assembler = RoundAssembler(db)
                rnd = await assembler.assemble_and_publish(topic.value)
                if rnd:
                    logger.info("  → Published round: '%s'", rnd.title)
                else:
                    logger.info("  → Not enough questions for a new round")
                await db.commit()

    logger.info("=" * 60)
    logger.info("NIGHTLY PIPELINE COMPLETE")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Nightly Quiz Pipeline")
    parser.add_argument(
        "--topic",
        default="all",
        help="Topic to process, or 'all'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip AI gate and don't publish rounds",
    )
    args = parser.parse_args()

    if args.topic == "all":
        topics = list(TOPIC_MAP.keys())
    else:
        topics = [args.topic]

    asyncio.run(run(topics, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
