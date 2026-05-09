"""
OMDB source — fetches structured film data from the Open Movie Database.

Requires an API key (free tier: 1000 requests/day).
Produces one Factoid per film with rich attribute data.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from models.domain import Topic, Factoid
from models.interfaces import ITrawlerSource

logger = logging.getLogger(__name__)

# Curated seed lists per decade — avoids over-indexing on blockbusters.
# The trawler uses these as starting points; Wikipedia cross-references
# fill in deeper cuts.
_SEED_FILMS: dict[str, list[str]] = {
    "2010s_wide": [
        "tt1375666", "tt2562232", "tt1853728", "tt2084970", "tt2380307",
        "tt3783958", "tt5013056", "tt4154756", "tt1950186", "tt3659388",
    ],
    "2010s_indie": [
        "tt3170832", "tt2119532", "tt4846340", "tt5580390", "tt7131622",
        "tt4925292", "tt5052448", "tt1790809", "tt2582802", "tt2798920",
    ],
    "2020s_wide": [
        "tt1160419", "tt10872600", "tt9032400", "tt15398776", "tt14230458",
        "tt6718170", "tt11286314", "tt14208870", "tt13238346", "tt14444726",
    ],
    "2020s_indie": [
        "tt14039582", "tt7740496", "tt13833688", "tt11271038", "tt14849194",
        "tt6857112", "tt12789558", "tt15742898", "tt14443502", "tt14826022",
    ],
}


class OMDBSource(ITrawlerSource):
    """Scrapes film data from OMDB API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def source_name(self) -> str:
        return "omdb"

    @property
    def supported_topics(self) -> list[Topic]:
        return [Topic.MOVIES]

    async def scrape(self, topic: Topic, limit: int = 50) -> list[Factoid]:
        if topic != Topic.MOVIES:
            return []

        # Collect IMDb IDs from seed lists up to the limit
        all_ids: list[str] = []
        for group in _SEED_FILMS.values():
            all_ids.extend(group)
        ids_to_fetch = all_ids[:limit]

        factoids: list[Factoid] = []
        async with aiohttp.ClientSession() as session:
            for imdb_id in ids_to_fetch:
                try:
                    factoid = await self._fetch_one(session, imdb_id)
                    if factoid:
                        factoids.append(factoid)
                except Exception as exc:
                    logger.warning("Failed to fetch %s: %s", imdb_id, exc)

                # Be polite — OMDB free tier is rate-limited
                await asyncio.sleep(0.25)

        logger.info("OMDB scraped %d films", len(factoids))
        return factoids

    async def _fetch_one(
        self, session: aiohttp.ClientSession, imdb_id: str
    ) -> Factoid | None:
        url = "https://www.omdbapi.com/"
        params = {"i": imdb_id, "apikey": self._api_key, "plot": "full"}

        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                return None
            data: dict[str, Any] = await resp.json()

        if data.get("Response") == "False":
            return None

        return Factoid(
            entity_id=imdb_id,
            topic=Topic.MOVIES,
            entity_name=data.get("Title", ""),
            source=self.source_name,
            attributes={
                "year": _safe_int(data.get("Year")),
                "director": data.get("Director"),
                "cast": _split(data.get("Actors")),
                "genre": _split(data.get("Genre")),
                "awards": data.get("Awards"),
                "plot": data.get("Plot"),
                "box_office": data.get("BoxOffice"),
                "runtime_min": _parse_runtime(data.get("Runtime")),
                "imdb_rating": _safe_float(data.get("imdbRating")),
                "metascore": _safe_int(data.get("Metascore")),
                "rated": data.get("Rated"),
                "country": data.get("Country"),
                "language": data.get("Language"),
                "poster_url": data.get("Poster"),
            },
        )


def _split(val: str | None) -> list[str]:
    if not val or val == "N/A":
        return []
    return [s.strip() for s in val.split(",")]


def _safe_int(val: Any) -> int | None:
    try:
        return int(str(val).replace(",", "").split("–")[0])
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_runtime(val: str | None) -> int | None:
    if not val or val == "N/A":
        return None
    try:
        return int(val.replace(" min", "").strip())
    except ValueError:
        return None
