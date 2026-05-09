"""
Wikipedia source — fetches structured data via the MediaWiki API.

Multi-topic: works for movies, music, science, history, geography,
sport, food, and nature by using curated category trees.

No API key required. Rate-limited to be respectful.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from models.domain import Topic, Factoid
from models.interfaces import ITrawlerSource

logger = logging.getLogger(__name__)

_WIKI_API = "https://en.wikipedia.org/w/api.php"

# Maps topics to Wikipedia categories for discovery.
# The trawler walks these categories to find entity pages.
_CATEGORY_SEEDS: dict[Topic, list[str]] = {
    Topic.MOVIES: [
        "Category:2020s_English-language_films",
        "Category:2010s_English-language_films",
        "Category:Films_that_won_the_Best_Picture_Academy_Award",
    ],
    Topic.MUSIC: [
        "Category:2020s_albums",
        "Category:2010s_albums",
        "Category:Grammy_Award_for_Album_of_the_Year",
    ],
    Topic.SCIENCE: [
        "Category:Scientific_discoveries",
        "Category:Physics_phenomena",
        "Category:Human_biology",
    ],
    Topic.HISTORY: [
        "Category:Historical_events",
        "Category:20th-century_conflicts",
        "Category:Ancient_civilizations",
    ],
    Topic.GEOGRAPHY: [
        "Category:Countries",
        "Category:Capital_cities",
        "Category:Extreme_points_of_Earth",
    ],
    Topic.SPORT: [
        "Category:Olympic_sports",
        "Category:World_records_in_athletics",
        "Category:FIFA_World_Cup",
    ],
    Topic.FOOD: [
        "Category:Cuisines",
        "Category:Alcoholic_drinks",
        "Category:Spices",
    ],
    Topic.NATURE: [
        "Category:Mammals",
        "Category:Endangered_species",
        "Category:Botanical_phenomena",
    ],
}


class WikipediaSource(ITrawlerSource):
    """Scrapes entity data from Wikipedia via the MediaWiki API."""

    @property
    def source_name(self) -> str:
        return "wikipedia"

    @property
    def supported_topics(self) -> list[Topic]:
        return list(_CATEGORY_SEEDS.keys())

    async def scrape(self, topic: Topic, limit: int = 50) -> list[Factoid]:
        categories = _CATEGORY_SEEDS.get(topic, [])
        if not categories:
            return []

        titles: list[str] = []
        async with aiohttp.ClientSession() as session:
            for cat in categories:
                if len(titles) >= limit:
                    break
                batch = await self._list_category(session, cat, limit - len(titles))
                titles.extend(batch)

            factoids: list[Factoid] = []
            for title in titles[:limit]:
                try:
                    factoid = await self._fetch_page(session, title, topic)
                    if factoid:
                        factoids.append(factoid)
                except Exception as exc:
                    logger.warning("Failed to fetch '%s': %s", title, exc)
                await asyncio.sleep(0.1)

        logger.info("Wikipedia scraped %d entities for '%s'", len(factoids), topic.value)
        return factoids

    async def _list_category(
        self, session: aiohttp.ClientSession, category: str, limit: int
    ) -> list[str]:
        """Get page titles from a Wikipedia category."""
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": "page",
            "cmlimit": min(limit, 50),
            "format": "json",
        }
        async with session.get(_WIKI_API, params=params) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()

        members = data.get("query", {}).get("categorymembers", [])
        return [m["title"] for m in members]

    async def _fetch_page(
        self,
        session: aiohttp.ClientSession,
        title: str,
        topic: Topic,
    ) -> Factoid | None:
        """Fetch structured extract + infobox-like data for a page."""
        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts|pageprops|revisions|categories",
            "exintro": True,
            "explaintext": True,
            "rvprop": "content",
            "rvslots": "main",
            "rvsection": "0",
            "format": "json",
        }
        async with session.get(_WIKI_API, params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), None)
        if not page or "missing" in page:
            return None

        extract = page.get("extract", "")
        wikitext = ""
        revisions = page.get("revisions", [])
        if revisions:
            wikitext = revisions[0].get("slots", {}).get("main", {}).get("*", "")

        # Parse structured attributes from the wikitext infobox
        attributes = self._parse_infobox(wikitext)
        attributes["extract"] = extract
        attributes["categories"] = [
            c["title"].replace("Category:", "")
            for c in page.get("categories", [])
        ]

        page_id = str(page.get("pageid", title))

        return Factoid(
            entity_id=f"wiki:{page_id}",
            topic=topic,
            entity_name=title,
            source=self.source_name,
            attributes=attributes,
        )

    @staticmethod
    def _parse_infobox(wikitext: str) -> dict[str, Any]:
        """
        Naive infobox parser — extracts key=value pairs from
        {{ Infobox ... }} blocks in wikitext.

        This is intentionally simple. A production version would
        use mwparserfromhell for proper template parsing.
        """
        attrs: dict[str, Any] = {}
        in_infobox = False
        for line in wikitext.split("\n"):
            stripped = line.strip()
            if stripped.lower().startswith("{{infobox") or stripped.lower().startswith("{{ infobox"):
                in_infobox = True
                continue
            if in_infobox:
                if stripped == "}}":
                    in_infobox = False
                    continue
                if stripped.startswith("|") and "=" in stripped:
                    key, _, val = stripped[1:].partition("=")
                    key = key.strip().lower().replace(" ", "_")
                    val = _clean_wikitext(val.strip())
                    if key and val:
                        attrs[key] = val
        return attrs


def _clean_wikitext(text: str) -> str:
    """Strip basic wiki markup from a value."""
    import re
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"{{[^}]*}}", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text)
    text = re.sub(r"<ref[^/]*/>", "", text)
    text = re.sub(r"'''?", "", text)
    return text.strip()
