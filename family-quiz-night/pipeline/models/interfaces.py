"""
Abstract interfaces for the three pipeline stages.

Every concrete implementation must conform to these contracts.
This is the single source of truth for inter-stage communication.
"""

from abc import ABC, abstractmethod

from models.domain import (
    Topic,
    Factoid,
    QuestionCandidate,
    QualityResult,
    ApprovedQuestion,
)


class ITrawlerSource(ABC):
    """
    Stage 1 contract — a single data source that produces Factoids.

    Each source (OMDB, Wikipedia, MusicBrainz, etc.) implements this.
    The orchestrator calls `scrape()` and gets back normalised Factoids
    regardless of where the data came from.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this source, e.g. 'omdb', 'wikipedia'."""
        ...

    @property
    @abstractmethod
    def supported_topics(self) -> list[Topic]:
        """Which topics this source can provide data for."""
        ...

    @abstractmethod
    async def scrape(self, topic: Topic, limit: int = 50) -> list[Factoid]:
        """
        Fetch and normalise data for the given topic.

        Args:
            topic:  Which topic to scrape for.
            limit:  Max number of Factoids to return per call.

        Returns:
            List of Factoids, each representing one entity.
        """
        ...


class IQuestionGenerator(ABC):
    """
    Stage 2 contract — transforms Factoids into QuestionCandidates.

    Pure logic, no AI, no network calls. Deterministic templates
    that know how to read each topic's attribute schema and produce
    interesting question/answer pairs.
    """

    @property
    @abstractmethod
    def supported_topics(self) -> list[Topic]:
        """Which topics this generator handles."""
        ...

    @abstractmethod
    def generate(self, factoid: Factoid) -> list[QuestionCandidate]:
        """
        Produce question candidates from a single Factoid.

        Should produce 20-30 candidates per Factoid. Many will be
        filtered out by Stage 3 — that's by design. Over-generate,
        then curate.

        Args:
            factoid: A structured data blob from Stage 1.

        Returns:
            List of QuestionCandidates (unvetted).
        """
        ...


class IQualityGate(ABC):
    """
    Stage 3 contract — AI-powered quality filter.

    This is the ONLY stage that uses AI tokens. It scores each
    candidate for clarity, fun factor, and difficulty accuracy,
    then either approves, requests a rewrite, or rejects.

    Designed for batch processing to minimise API calls.
    """

    @abstractmethod
    async def evaluate(
        self, candidates: list[QuestionCandidate]
    ) -> list[QualityResult]:
        """
        Score and filter a batch of candidates.

        Batches candidates into a single prompt where possible
        to reduce token usage. Typical batch size: 20-30.

        Args:
            candidates: Unvetted questions from Stage 2.

        Returns:
            One QualityResult per candidate.
        """
        ...


class IFactoidStore(ABC):
    """
    Persistence contract for Factoids.

    Allows deduplication and incremental scraping — the trawler
    checks what we already have before hitting external APIs.
    """

    @abstractmethod
    async def save(self, factoid: Factoid) -> None:
        ...

    @abstractmethod
    async def exists(self, entity_id: str, source: str) -> bool:
        ...

    @abstractmethod
    async def get_by_topic(self, topic: Topic, limit: int = 100) -> list[Factoid]:
        ...


class IQuestionStore(ABC):
    """
    Persistence contract for approved questions.

    Supports querying by topic for round assembly.
    """

    @abstractmethod
    async def save(self, question: ApprovedQuestion) -> None:
        ...

    @abstractmethod
    async def get_by_topic(
        self, topic: Topic, limit: int = 20, min_score: float = 0.0
    ) -> list[ApprovedQuestion]:
        ...

    @abstractmethod
    async def count_by_topic(self, topic: Topic) -> int:
        ...
