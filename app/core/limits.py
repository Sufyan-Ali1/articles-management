import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass

from app.core.errors import APIError


@dataclass(frozen=True)
class Limit:
    key: str
    count: int
    seconds: int


class RateLimiter:
    """Atomic sliding windows on one event loop; never evict live keys to admit traffic."""

    def __init__(self, max_keys: int = 10000) -> None:
        self.max_keys = max_keys
        self._entries: dict[tuple[str, int], deque[float]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = 0.0

    async def check(self, *limits: Limit) -> None:
        now = time.monotonic()
        async with self._lock:
            if now - self._last_cleanup >= 30 or len(self._entries) + len(limits) > self.max_keys:
                self._entries = {k: q for k, q in self._entries.items() if q and q[-1] > now - k[1]}
                self._last_cleanup = now
            missing = {(item.key, item.seconds) for item in limits} - self._entries.keys()
            if len(self._entries) + len(missing) > self.max_keys:
                raise APIError(
                    429, "rate_limited", "Please try again later", headers={"Retry-After": "60"}
                )
            for item in limits:
                queue = self._entries.get((item.key, item.seconds), deque())
                while queue and queue[0] <= now - item.seconds:
                    queue.popleft()
                if len(queue) >= item.count:
                    retry = max(1, math.ceil(queue[0] + item.seconds - now))
                    raise APIError(
                        429,
                        "rate_limited",
                        "Please try again later",
                        headers={"Retry-After": str(retry)},
                    )
            for item in limits:
                self._entries.setdefault((item.key, item.seconds), deque()).append(now)
