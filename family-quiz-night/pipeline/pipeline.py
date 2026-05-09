"""
Quiz Pipeline — orchestrates the three-stage process:

  Stage 1: Trawl    → scrape structured data into Factoids
  Stage 2: Generate → deterministic templates produce QuestionCandidates
  Stage 3: Curate   → AI quality gate approves/rewrites/rejects

Usage:
    python pipeline.py --topic movies --omdb-key YOUR_KEY --anthropic-key YOUR_KEY
    python pipeline.py --topic all --omdb-key YOUR_KEY --anthropic-key YOUR_KEY
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import sys
from pathlib import Path

from config import PipelineConfig
from models.domain import Topic, ApprovedQuestion, QualityVerdict
from models.interfaces import IFactoidStore, IQuestionStore
from trawler import TrawlerOrchestrator
from trawler.sources import OMDBSource, WikipediaSource
from generator import QuestionEngine
from quality_gate import ClaudeQualityGate
from storage import JsonFactoidStore, JsonQuestionStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


async def run_pipeline(config: PipelineConfig) -> dict[Topic, int]:
    """
    Execute the full three-stage pipeline.

    Returns a dict of topic → number of approved questions produced.
    """
    # ── Initialise stores ──
    factoid_store: IFactoidStore = JsonFactoidStore(config.factoid_store_path)
    question_store: IQuestionStore = JsonQuestionStore(config.question_store_path)

    # ── Stage 1: Trawl ──
    trawler = TrawlerOrchestrator(store=factoid_store)

    if config.omdb_api_key:
        trawler.register(OMDBSource(api_key=config.omdb_api_key))
    trawler.register(WikipediaSource())

    results: dict[Topic, int] = {}

    for topic in config.topics_to_scrape:
        logger.info("═" * 60)
        logger.info("TOPIC: %s", topic.value.upper())
        logger.info("═" * 60)

        # Stage 1
        logger.info("Stage 1 — Trawling...")
        new_factoids = await trawler.run(topic, config.scrape_limit_per_source)

        # Also include previously scraped factoids for generation
        all_factoids = await factoid_store.get_by_topic(topic, limit=200)
        logger.info(
            "Total factoids available for '%s': %d (%d new)",
            topic.value, len(all_factoids), len(new_factoids),
        )

        if not all_factoids:
            logger.warning("No factoids for '%s' — skipping", topic.value)
            results[topic] = 0
            continue

        # Stage 2
        logger.info("Stage 2 — Generating candidates...")
        engine = QuestionEngine()
        candidates = engine.generate_batch(all_factoids)
        logger.info("Produced %d candidates", len(candidates))

        if not candidates:
            results[topic] = 0
            continue

        # Stage 3
        if config.anthropic_api_key:
            logger.info("Stage 3 — Quality gate...")
            gate = ClaudeQualityGate(
                api_key=config.anthropic_api_key,
                model=config.quality_model,
            )
            quality_results = await gate.evaluate(candidates)

            # Build lookup
            qr_map = {r.candidate_id: r for r in quality_results}
            approved_count = 0

            for candidate in candidates:
                qr = qr_map.get(candidate.id)
                if not qr:
                    continue

                if qr.verdict == QualityVerdict.APPROVED and qr.score >= config.min_approval_score:
                    approved = ApprovedQuestion(
                        question=candidate.question,
                        answer=candidate.answer,
                        topic=candidate.topic,
                        difficulty=candidate.difficulty,
                        score=qr.score,
                        tags=candidate.tags,
                        source_entity=candidate.source_factoid_id,
                    )
                    await question_store.save(approved)
                    approved_count += 1

                elif qr.verdict == QualityVerdict.REWRITE and qr.rewritten_question:
                    approved = ApprovedQuestion(
                        question=qr.rewritten_question,
                        answer=qr.rewritten_answer or candidate.answer,
                        topic=candidate.topic,
                        difficulty=candidate.difficulty,
                        score=qr.score,
                        tags=candidate.tags,
                        source_entity=candidate.source_factoid_id,
                    )
                    await question_store.save(approved)
                    approved_count += 1

            results[topic] = approved_count
        else:
            # No AI key — save all candidates as-is (for testing)
            logger.warning("No Anthropic key — skipping Stage 3, saving all candidates")
            for candidate in candidates:
                approved = ApprovedQuestion(
                    question=candidate.question,
                    answer=candidate.answer,
                    topic=candidate.topic,
                    difficulty=candidate.difficulty,
                    score=0.5,
                    tags=candidate.tags,
                    source_entity=candidate.source_factoid_id,
                )
                await question_store.save(approved)
            results[topic] = len(candidates)

        total = await question_store.count_by_topic(topic)
        logger.info("Total approved questions for '%s': %d", topic.value, total)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Quiz Question Pipeline")
    parser.add_argument(
        "--topic",
        default="all",
        help="Topic to process (or 'all')",
    )
    parser.add_argument("--omdb-key", default="", help="OMDB API key")
    parser.add_argument("--anthropic-key", default="", help="Anthropic API key")
    parser.add_argument("--limit", type=int, default=50, help="Max entities per source")
    parser.add_argument("--data-dir", default="./data", help="Data directory")
    args = parser.parse_args()

    config = PipelineConfig(
        omdb_api_key=args.omdb_key,
        anthropic_api_key=args.anthropic_key,
        scrape_limit_per_source=args.limit,
        data_dir=Path(args.data_dir),
    )

    if args.topic == "all":
        config.topics_to_scrape = list(Topic)
    else:
        try:
            config.topics_to_scrape = [Topic(args.topic)]
        except ValueError:
            logger.error("Unknown topic: %s", args.topic)
            sys.exit(1)

    results = asyncio.run(run_pipeline(config))

    logger.info("═" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("═" * 60)
    for topic, count in results.items():
        logger.info("  %s: %d approved questions", topic.value, count)


if __name__ == "__main__":
    main()
