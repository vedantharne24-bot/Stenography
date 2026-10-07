"""Sliding-window rate limiter.

In-process implementation suitable for a single API worker. For multi-worker
deployments put the same policy in front of the app (reverse proxy) or swap the
store for Redis - the ``RateLimiter`` interface stays the same.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimited


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(window - (now - hits[0])) + 1)
                raise RateLimited(
                    "Too many requests. Slow down and retry shortly.", details={"retry_after": retry_after}
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit_attr: str) -> Callable[[Request], None]:
    """FastAPI dependency factory: ``Depends(rate_limit("auth", "rate_limit_auth"))``."""

    def _dependency(request: Request) -> None:
        settings = get_settings()
        limit = int(getattr(settings, limit_attr))
        limiter.check(f"{bucket}:{client_ip(request)}", limit, settings.rate_limit_window_seconds)

    return _dependency
