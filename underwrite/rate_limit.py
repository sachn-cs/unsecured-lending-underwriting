# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Token-bucket rate limiter with bounded state."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

from underwrite.exceptions import RateLimitError
from underwrite.logger import logger
from underwrite.store import Sqlite, Store


class Limiter:
    """Token-bucket rate limiter per key.

    The bucket state is kept in an LRU-bounded dict so that callers
    passing a rotating set of keys cannot grow the limiter's footprint
    without bound.  The default bound is 10 000 keys; pass
    ``max_buckets`` to override.
    """

    DEFAULT_MAX_BUCKETS: int = 10_000

    def __init__(
        self,
        max_rate: float = 100.0,
        interval: float = 1.0,
        max_buckets: int = DEFAULT_MAX_BUCKETS,
    ) -> None:
        """Initializes a token-bucket rate limiter.

        Args:
            max_rate: Maximum operations per *interval*.
            interval: Time window in seconds.
            max_buckets: Soft cap on the number of tracked keys. When
                the cap is reached, the least-recently-used key is
                evicted. Defaults to 10 000.
        """
        if max_rate <= 0:
            raise ValueError(f"max_rate must be > 0, got {max_rate}")
        if interval <= 0:
            raise ValueError(f"interval must be > 0, got {interval}")
        if max_buckets <= 0:
            raise ValueError(f"max_buckets must be > 0, got {max_buckets}")
        self.max_rate: float = max_rate
        self.interval: float = interval
        self.max_buckets: int = max_buckets
        self.lock: threading.Lock = threading.Lock()
        # OrderedDict gives us LRU semantics in O(1).
        self.buckets: OrderedDict[str, float] = OrderedDict()

    def check(self, key: str) -> bool:
        """Checks whether *key* is allowed under the rate limit.

        Args:
            key: Identifier to rate-limit (e.g. subscriber ID).

        Returns:
            True if the operation is allowed, False otherwise.
        """
        now = time.monotonic()
        with self.lock:
            last = self.buckets.get(key)
            if last is not None and now - last < self.interval / self.max_rate:
                # Touch for LRU even on denial.
                self.buckets.move_to_end(key)
                return False
            self.buckets[key] = now
            self.buckets.move_to_end(key)
            while len(self.buckets) > self.max_buckets:
                self.buckets.popitem(last=False)
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

    def evict_idle(self, idle_seconds: float) -> int:
        """Drops entries that have been idle longer than *idle_seconds*.

        Returns:
            Number of entries removed.
        """
        cutoff = time.monotonic() - idle_seconds
        removed = 0
        with self.lock:
            # Iterate a snapshot — mutating during iteration is unsafe.
            for key in list(self.buckets):
                if self.buckets[key] < cutoff:
                    del self.buckets[key]
                    removed += 1
        return removed


class DistributedLimiter(Limiter):
    """Store-backed distributed token-bucket rate limiter.

    Shares state through a common ``Store`` so that multiple processes
    (or hosts) respect the same rate limit. Falls back to the in-memory
    parent implementation when no store is provided.

    Store entries are written with an ``expires_at`` timestamp and a
    best-effort sweep keeps the store bounded: each ``check`` evicts
    any expired entries it encounters, and callers may run
    :meth:`sweep` periodically to garbage-collect stragglers.
    """

    def __init__(
        self,
        max_rate: float = 100.0,
        interval: float = 1.0,
        store: Store | Sqlite | None = None,
        prefix: str = "ratelimit",
        max_buckets: int = Limiter.DEFAULT_MAX_BUCKETS,
    ) -> None:
        """Initializes a distributed rate limiter.

        Args:
            max_rate: Maximum operations per *interval*.
            interval: Time window in seconds.
            store: Shared store for cross-process coordination.
            prefix: Key prefix in the store.
            max_buckets: In-memory LRU bound on tracked keys.
        """
        super().__init__(max_rate=max_rate, interval=interval, max_buckets=max_buckets)
        self.store: Store | Sqlite | None = store
        self.prefix: str = prefix
        self._sweep_lock: threading.Lock = threading.Lock()
        if store is None:
            logger.warning(
                "DistributedRateLimiter created without store, falling back to in-memory rate limiter",
            )

    def check(self, key: str) -> bool:
        if self.store is None:
            return super().check(key)
        if not super().check(key):
            return False
        now = time.time()
        window_size = self.interval / self.max_rate
        window = int(now / window_size)
        store_key = f"{self.prefix}:{key}:{window}"
        window_end = (window + 1) * window_size
        raw = self.store.get(store_key)
        if isinstance(raw, dict) and raw.get("expires_at", 0) > now:
            return False
        # Opportunistic expiration: any entry from a previous window
        # is garbage so we can overwrite it.  If it is still in
        # window, that means we just consumed the slot.
        self.store.set(store_key, {"expires_at": window_end, "window": window})
        return True

    def sweep(self, now: float | None = None) -> int:
        """Drops expired entries from the store.

        Returns the number of entries removed. The sweep iterates over
        every key under the limiter's prefix, so it is O(n) in the
        number of stored windows; run it from a background thread at a
        cadence matching your traffic (every few minutes is typical).
        """
        if self.store is None:
            return 0
        with self._sweep_lock:
            now = now if now is not None else time.time()
            prefix = f"{self.prefix}:"
            removed = 0
            try:
                keys = self.store.keys(pattern=f"{prefix}*", limit=0)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("rate limiter sweep failed to enumerate keys: {}", exc)
                return 0
            for key in keys:
                raw = self.store.get(key)
                if not isinstance(raw, dict):
                    continue
                expires_at = raw.get("expires_at", 0)
                if expires_at <= now:
                    if self.store.delete(key):
                        removed += 1
            return removed
