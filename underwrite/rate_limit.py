"""Token-bucket rate limiter."""

from __future__ import annotations

import threading
import time

from underwrite.exceptions import RateLimitError
from underwrite.logger import logger
from underwrite.store import Store


class Limiter:
    """Token-bucket rate limiter per key."""

    def __init__(self, max_rate: float = 100.0, interval: float = 1.0) -> None:
        """Initializes a token-bucket rate limiter.

        Args:
            max_rate: Maximum operations per *interval*.
            interval: Time window in seconds.
        """
        self.max_rate: float = max_rate
        self.interval: float = interval
        self.__lock: threading.Lock = threading.Lock()
        self.__buckets: dict[str, float] = {}

    def check(self, key: str) -> bool:
        """Checks whether *key* is allowed under the rate limit.

        Args:
            key: Identifier to rate-limit (e.g. subscriber ID).

        Returns:
            True if the operation is allowed, False otherwise.
        """
        if self.max_rate == 0:
            return True
        now = time.monotonic()
        with self.__lock:
            last = self.__buckets.get(key, 0.0)
            if now - last < self.interval / self.max_rate:
                return False
            self.__buckets[key] = now
            return True

    def assert_allowed(self, key: str) -> None:
        """Asserts that *key* is under the rate limit, raising otherwise.

        Args:
            key: Identifier to rate-limit.

        Raises:
            RateLimitError: If the rate limit is exceeded.
        """
        if not self.check(key):
            raise RateLimitError(f"rate limit exceeded for {key}")


class DistributedLimiter(Limiter):
    """Store-backed distributed token-bucket rate limiter.

    Shares state through a common ``Store`` so that multiple processes
    (or hosts) respect the same rate limit.  Falls back to the in-memory
    parent implementation when no store is provided.
    """

    def __init__(
        self,
        max_rate: float = 100.0,
        interval: float = 1.0,
        store: Store | None = None,
        prefix: str = "ratelimit",
    ) -> None:
        """Initializes a distributed rate limiter.

        Args:
            max_rate: Maximum operations per *interval*.
            interval: Time window in seconds.
            store: Shared store for cross-process coordination.
            prefix: Key prefix in the store.
        """
        super().__init__(max_rate=max_rate, interval=interval)
        self.__store: Store | None = store
        self.__prefix: str = prefix
        if store is None:
            logger.warning("DistributedRateLimiter created without store, falling back to in-memory rate limiter")

    def check(self, key: str) -> bool:
        if self.__store is None:
            return super().check(key)
        if not super().check(key):
            return False
        now = time.time()
        window = int(now / (self.interval / self.max_rate))
        store_key = f"{self.__prefix}:{key}:{window}"
        window_end = (window + 1) * (self.interval / self.max_rate)
        raw = self.__store.get(store_key)
        if isinstance(raw, dict) and raw.get("expires_at", 0) > now:
            return False
        self.__store.set(store_key, {"expires_at": window_end})
        return True
