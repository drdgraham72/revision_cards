"""
Question engine — Stage 2 of the pipeline.

Takes Factoids, runs all matching templates, and produces
QuestionCandidates. Pure logic, zero AI, zero network calls.
"""

from __future__ import annotations

import logging

from models.domain import Factoid, QuestionCandidate
from models.interfaces import IQuestionGenerator, Topic
from generator.templates import get_templates

logger = logging.getLogger(__name__)


class QuestionEngine(IQuestionGenerator):
    """
    Deterministic question generator.

    Runs every registered template for a Factoid's topic and collects
    the results. Over-generates by design — Stage 3 curates.
    """

    @property
    def supported_topics(self) -> list[Topic]:
        return list(Topic)

    def generate(self, factoid: Factoid) -> list[QuestionCandidate]:
        templates = get_templates(factoid.topic)
        candidates: list[QuestionCandidate] = []

        for tmpl in templates:
            try:
                result = tmpl.fn(factoid)
            except Exception as exc:
                logger.warning(
                    "Template '%s' failed for factoid '%s': %s",
                    tmpl.id, factoid.entity_name, exc,
                )
                continue

            if result is None:
                continue

            question, answer, difficulty, template_id, tags = result
            candidates.append(
                QuestionCandidate(
                    question=question,
                    answer=answer,
                    topic=factoid.topic,
                    difficulty=difficulty,
                    source_factoid_id=factoid.id,
                    template_id=template_id,
                    tags=tags,
                )
            )

        logger.debug(
            "Generated %d candidates from '%s' (%s)",
            len(candidates), factoid.entity_name, factoid.topic.value,
        )
        return candidates

    def generate_batch(self, factoids: list[Factoid]) -> list[QuestionCandidate]:
        """Run generation across multiple factoids."""
        all_candidates: list[QuestionCandidate] = []
        for factoid in factoids:
            all_candidates.extend(self.generate(factoid))

        logger.info(
            "Generated %d total candidates from %d factoids",
            len(all_candidates), len(factoids),
        )
        return all_candidates
