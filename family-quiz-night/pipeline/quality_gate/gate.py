"""
Claude quality gate — Stage 3 of the pipeline.

This is the ONLY stage that spends AI tokens. It batches candidates
into a single prompt, asks Claude to score each one, and parses
the structured response.

Designed to be token-efficient:
  - Batches 20-30 candidates per API call
  - Uses structured JSON output
  - Single-shot evaluation (no multi-turn)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from models.domain import QuestionCandidate, QualityResult, QualityVerdict
from models.interfaces import IQualityGate

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a quiz quality assessor for a family quiz night app.

You will receive a batch of question/answer candidates. For EACH one, evaluate:

1. **clarity** (0.0–1.0): Is the question unambiguous? Would a smart person understand what's being asked?
2. **fun_factor** (0.0–1.0): Is this enjoyable to answer? Does it spark conversation or debate?
3. **difficulty_accurate** (true/false): Does the stated difficulty match the actual difficulty?
4. **verdict**: "approved", "rewrite", or "rejected"
   - approved: Good to go as-is
   - rewrite: The core idea is good but the wording needs work (provide rewritten_question and rewritten_answer)
   - rejected: Too boring, too obscure, factually shaky, or just not fun
5. **reason**: Brief explanation of your verdict (1 sentence)

Scoring guidelines:
- Reject questions that are trivially Googleable with no "aha" moment
- Reject questions that are so obscure nobody would enjoy them
- Prefer questions with surprising answers or that spark debate
- Rewrite questions that have a good core but clunky phrasing
- Approve questions that make you think "ooh, that's a good one"

Respond with ONLY a JSON array. No markdown, no preamble. Each element:
{
  "candidate_id": "...",
  "clarity": 0.0-1.0,
  "fun_factor": 0.0-1.0,
  "difficulty_accurate": true/false,
  "verdict": "approved|rewrite|rejected",
  "reason": "...",
  "rewritten_question": "..." or null,
  "rewritten_answer": "..." or null
}
"""

_BATCH_SIZE = 25  # Sweet spot for token efficiency vs context quality


class ClaudeQualityGate(IQualityGate):
    """
    Uses the Anthropic Messages API to evaluate question candidates in batches.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self._api_key = api_key
        self._model = model
        self._api_url = "https://api.anthropic.com/v1/messages"

    async def evaluate(
        self, candidates: list[QuestionCandidate]
    ) -> list[QualityResult]:
        results: list[QualityResult] = []

        # Process in batches
        for i in range(0, len(candidates), _BATCH_SIZE):
            batch = candidates[i : i + _BATCH_SIZE]
            batch_results = await self._evaluate_batch(batch)
            results.extend(batch_results)

        approved = sum(1 for r in results if r.verdict == QualityVerdict.APPROVED)
        rewrite = sum(1 for r in results if r.verdict == QualityVerdict.REWRITE)
        rejected = sum(1 for r in results if r.verdict == QualityVerdict.REJECTED)
        logger.info(
            "Quality gate: %d approved, %d rewrite, %d rejected (of %d)",
            approved, rewrite, rejected, len(results),
        )
        return results

    async def _evaluate_batch(
        self, batch: list[QuestionCandidate]
    ) -> list[QualityResult]:
        """Send a single batch to Claude and parse the response."""

        # Format candidates for the prompt
        items = []
        for c in batch:
            items.append({
                "candidate_id": c.id,
                "question": c.question,
                "answer": c.answer,
                "topic": c.topic.value,
                "difficulty": c.difficulty.value,
                "template": c.template_id,
                "tags": c.tags,
            })

        user_message = json.dumps(items, indent=2)

        payload = {
            "model": self._model,
            "max_tokens": 4096,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._api_url, json=payload, headers=headers
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("API error %d: %s", resp.status, body)
                    # Return all as rejected on API failure
                    return [
                        QualityResult(
                            candidate_id=c.id,
                            verdict=QualityVerdict.REJECTED,
                            score=0.0,
                            clarity=0.0,
                            fun_factor=0.0,
                            difficulty_accurate=False,
                            reason=f"API error: {resp.status}",
                        )
                        for c in batch
                    ]

                data = await resp.json()

        # Extract text content from response
        raw_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                raw_text += block.get("text", "")

        return self._parse_response(raw_text, batch)

    def _parse_response(
        self, raw_text: str, batch: list[QuestionCandidate]
    ) -> list[QualityResult]:
        """Parse Claude's JSON response into QualityResult objects."""
        # Strip any markdown fencing
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]

        try:
            evaluations: list[dict[str, Any]] = json.loads(text.strip())
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse quality gate response: %s", exc)
            return [
                QualityResult(
                    candidate_id=c.id,
                    verdict=QualityVerdict.REJECTED,
                    score=0.0,
                    clarity=0.0,
                    fun_factor=0.0,
                    difficulty_accurate=False,
                    reason="Parse error",
                )
                for c in batch
            ]

        # Index by candidate_id for lookup
        eval_map = {e["candidate_id"]: e for e in evaluations}
        results: list[QualityResult] = []

        for candidate in batch:
            e = eval_map.get(candidate.id)
            if not e:
                results.append(
                    QualityResult(
                        candidate_id=candidate.id,
                        verdict=QualityVerdict.REJECTED,
                        score=0.0,
                        clarity=0.0,
                        fun_factor=0.0,
                        difficulty_accurate=False,
                        reason="Missing from AI response",
                    )
                )
                continue

            clarity = float(e.get("clarity", 0))
            fun = float(e.get("fun_factor", 0))
            score = (clarity * 0.4) + (fun * 0.6)  # Fun-weighted composite

            verdict_str = e.get("verdict", "rejected").lower()
            try:
                verdict = QualityVerdict(verdict_str)
            except ValueError:
                verdict = QualityVerdict.REJECTED

            results.append(
                QualityResult(
                    candidate_id=candidate.id,
                    verdict=verdict,
                    score=score,
                    clarity=clarity,
                    fun_factor=fun,
                    difficulty_accurate=e.get("difficulty_accurate", False),
                    rewritten_question=e.get("rewritten_question"),
                    rewritten_answer=e.get("rewritten_answer"),
                    reason=e.get("reason", ""),
                )
            )

        return results
