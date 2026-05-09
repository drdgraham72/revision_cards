"""
JSON file-based storage — implements IFactoidStore and IQuestionStore.

Simple flat-file persistence for development. Swap for Postgres/SQLite
in production by implementing the same interfaces.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from models.domain import Topic, Factoid, ApprovedQuestion
from models.interfaces import IFactoidStore, IQuestionStore

logger = logging.getLogger(__name__)


class JsonFactoidStore(IFactoidStore):
    """Stores Factoids as newline-delimited JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("")

    async def save(self, factoid: Factoid) -> None:
        with open(self._path, "a") as f:
            record = asdict(factoid)
            record["topic"] = factoid.topic.value
            record["scraped_at"] = factoid.scraped_at.isoformat()
            f.write(json.dumps(record) + "\n")

    async def exists(self, entity_id: str, source: str) -> bool:
        for line in self._iter_lines():
            rec = json.loads(line)
            if rec["entity_id"] == entity_id and rec["source"] == source:
                return True
        return False

    async def get_by_topic(self, topic: Topic, limit: int = 100) -> list[Factoid]:
        results: list[Factoid] = []
        for line in self._iter_lines():
            rec = json.loads(line)
            if rec["topic"] == topic.value:
                results.append(self._to_factoid(rec))
                if len(results) >= limit:
                    break
        return results

    def _iter_lines(self):
        if not self._path.exists():
            return
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    yield line

    @staticmethod
    def _to_factoid(rec: dict) -> Factoid:
        from datetime import datetime
        return Factoid(
            entity_id=rec["entity_id"],
            topic=Topic(rec["topic"]),
            entity_name=rec["entity_name"],
            source=rec["source"],
            attributes=rec["attributes"],
            scraped_at=datetime.fromisoformat(rec["scraped_at"]),
            id=rec["id"],
        )


class JsonQuestionStore(IQuestionStore):
    """Stores ApprovedQuestions as newline-delimited JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("")

    async def save(self, question: ApprovedQuestion) -> None:
        with open(self._path, "a") as f:
            record = asdict(question)
            record["topic"] = question.topic.value
            record["difficulty"] = question.difficulty.value
            f.write(json.dumps(record) + "\n")

    async def get_by_topic(
        self, topic: Topic, limit: int = 20, min_score: float = 0.0
    ) -> list[ApprovedQuestion]:
        results: list[ApprovedQuestion] = []
        for line in self._iter_lines():
            rec = json.loads(line)
            if rec["topic"] == topic.value and rec.get("score", 0) >= min_score:
                results.append(self._to_question(rec))
                if len(results) >= limit:
                    break
        return results

    async def count_by_topic(self, topic: Topic) -> int:
        count = 0
        for line in self._iter_lines():
            rec = json.loads(line)
            if rec["topic"] == topic.value:
                count += 1
        return count

    def _iter_lines(self):
        if not self._path.exists():
            return
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    yield line

    @staticmethod
    def _to_question(rec: dict) -> ApprovedQuestion:
        return ApprovedQuestion(
            question=rec["question"],
            answer=rec["answer"],
            topic=Topic(rec["topic"]),
            difficulty=rec.get("difficulty", "medium"),
            score=rec.get("score", 0),
            tags=rec.get("tags", []),
            source_entity=rec.get("source_entity", ""),
            id=rec["id"],
        )
