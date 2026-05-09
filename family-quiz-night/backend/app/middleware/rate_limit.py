"""
Rate limiting — in-memory sliding window.

Two layers:
  1. Per-IP global limit (protects against brute force)
  2. Per-user answer reveal limit (anti-scrape)

In production, swap for Redis-backed limiter (e.g. via slowapi).
"""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status


class RateLimiter:
    """Sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int = 60) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        """Raises 429 if rate limit exceeded."""
        now = time.time()
        cutoff = now - self._window

        # Prune old hits
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]

        if len(self._hits[key]) >= self._max:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
            )

        self._hits[key].append(now)


# Singleton instances
global_limiter = RateLimiter(max_requests=200, window_seconds=60)
answer_limiter = RateLimiter(max_requests=60, window_seconds=60)


def get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
