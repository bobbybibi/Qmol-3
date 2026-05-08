"""In-memory token-bucket rate limiter, keyed by IP or API key.

Stateless-enough for a single worker; for multi-worker deployments, swap the
internal dict for Redis. Used to throttle:
  - POST /signup              (1/min per IP)
  - POST /compute  (free)     (60/min per IP)
  - POST /compute/premium     (600/min per API key)
"""
from __future__ import annotations
import threading
import time
from collections import defaultdict, deque

_LOCK = threading.Lock()
_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        self.retry_after = retry_after


def check(key: str, limit: int, window_seconds: float) -> None:
    """Raise RateLimited if caller has exceeded ``limit`` calls in the rolling window."""
    now = time.time()
    cutoff = now - window_seconds
    with _LOCK:
        q = _BUCKETS[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            retry = window_seconds - (now - q[0])
            raise RateLimited(retry_after=max(retry, 0.1))
        q.append(now)


def reset(key: str | None = None) -> None:
    with _LOCK:
        if key is None:
            _BUCKETS.clear()
        else:
            _BUCKETS.pop(key, None)
