"""
Trawler orchestrator — runs all registered sources for a given topic,
deduplicates against the store, and persists new Factoids.
"""

from __future__ import annotations

import asyncio
import logging

from models.domain import Topic, Factoid
from models.interfaces import ITrawlerSource, IFactoidStore

logger = logging.getLogger(__name__)


class TrawlerOrchestrator:
    """
    Coordinates multiple ITrawlerSource implementations.

    Register sources at startup, then call `run()` to scrape a topic
    across all sources that support it. Handles dedup and persistence.
    """

    def __init__(self, store: IFactoidStore) -> None:
        self._sources: list[ITrawlerSource] = []
        self._store = store

    def register(self, source: ITrawlerSource) -> None:
        self._sources.append(source)
        logger.info(
            "Registered source '%s' for topics: %s",
            source.source_name,
            [t.value for t in source.supported_topics],
        )

    async def run(self, topic: Topic, limit_per_source: int = 50) -> list[Factoid]:
        """
        Scrape all registered sources for the given topic.

        Returns only *new* Factoids (not already in the store).
        """
        relevant = [s for s in self._sources if topic in s.supported_topics]
        if not relevant:
            logger.warning("No sources registered for topic '%s'", topic.value)
            return []

        logger.info(
            "Running %d source(s) for topic '%s'", len(relevant), topic.value
        )

        tasks = [s.scrape(topic, limit_per_source) for s in relevant]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        new_factoids: list[Factoid] = []
        for source, result in zip(relevant, results):
            if isinstance(result, Exception):
                logger.error(
                    "Source '%s' failed: %s", source.source_name, result
                )
                continue

            for factoid in result:
                if await self._store.exists(factoid.entity_id, factoid.source):
                    logger.debug(
                        "Skipping duplicate: %s from %s",
                        factoid.entity_id, factoid.source,
                    )
                    continue

                await self._store.save(factoid)
                new_factoids.append(factoid)

        logger.info(
            "Trawled %d new factoids for topic '%s'",
            len(new_factoids), topic.value,
        )
        return new_factoids
