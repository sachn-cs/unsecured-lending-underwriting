"""Circuit breaker for resilient store and bus operations.

Tracks failure count and opens the circuit when a threshold is exceeded.
After a cooldown period, transitions to half-open for probation.
"""

from __future__ import annotations

__all__ = [
    "Breaker",
    "CircuitBreaker",
    "CircuitState",
    "RetryPolicy",
]

import secrets
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from underwrite.exceptions import CircuitBreakerOpenError
from underwrite.logger import logger


class CircuitState(Enum):
    """Circuit-breaker state: closed, open, or half-open."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker with configurable thresholds."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, name: str = "") -> None:
        """Initializes a circuit breaker.

        Args:
            failure_threshold: Consecutive failures before opening.
            recovery_timeout: Seconds before transitioning to half-open.
            name: Optional name for logging / debugging.
        """
        self.name: str = name
        self.failure_threshold: int = failure_threshold
        self.recovery_timeout: float = recovery_timeout
        self.lock: threading.Lock = threading.Lock()
        self.failure_count: int = 0
        self.last_failure_time: float = 0.0
        self._state: CircuitState = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        """Returns the current circuit state, potentially transitioning to half-open."""
        return self._get_state()

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Invokes a function under circuit-breaker protection.

        Args:
            fn: The callable to invoke.
            *args: Positional arguments for *fn*.
            **kwargs: Keyword arguments for *fn*.

        Returns:
            The return value of *fn*.

        Raises:
            CircuitBreakerOpenError: If the circuit is open.
        """
        state = self._get_state()
        if state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(f"circuit {self.name} is open")

        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _get_state(self) -> CircuitState:
        with self.lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self.last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info("circuit {} half-open (recovery timeout elapsed)", self.name)
            return self._state

    def _on_success(self) -> None:
        with self.lock:
            prev = self._state
            self.failure_count = 0
            self._state = CircuitState.CLOSED
        if prev != CircuitState.CLOSED:
            logger.info("circuit {} recovered ({} -> closed)", self.name, prev.value)

    def _on_failure(self) -> None:
        tripped = False
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.monotonic()
            if self.failure_count >= self.failure_threshold:
                if self._state != CircuitState.OPEN:
                    tripped = True
                self._state = CircuitState.OPEN
        count: int = self.failure_count
        logger.warning("circuit {} failure {}/{}", self.name, count, self.failure_threshold)
        if tripped:
            logger.warning("circuit {} tripped open ({} failures)", self.name, self.failure_threshold)


class RetryPolicy:
    """Exponential backoff retry with jitter.

    Only exceptions matching *retryable_exceptions* trigger a retry.
    All others are re-raised immediately.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 5.0,
        retryable_exceptions: tuple[type[Exception], ...] | None = None,
        non_retryable_exceptions: tuple[type[Exception], ...] | None = None,
    ) -> None:
        """Initializes a retry policy with exponential backoff.

        Args:
            max_retries: Maximum retry attempts (not counting the initial call).
            base_delay: Initial delay in seconds (doubled each retry).
            max_delay: Maximum delay cap in seconds.
            retryable_exceptions: Exception types that trigger retry.
                Defaults to ``(Exception,)`` (all exceptions).
            non_retryable_exceptions: Exception types that are
                re-raised immediately without retry. Defaults to
                ``(TypeError, ValueError, KeyError, AttributeError,
                NameError, IndexError)`` so that programmer errors
                are not silently retried.
        """
        self.max_retries: int = max_retries
        self.base_delay: float = base_delay
        self.max_delay: float = max_delay
        self.retryable_exceptions: tuple[type[Exception], ...] = retryable_exceptions or (Exception,)
        self.non_retryable_exceptions: tuple[type[Exception], ...] = non_retryable_exceptions or (
            TypeError,
            ValueError,
            KeyError,
            AttributeError,
            NameError,
            IndexError,
        )
        self.rng: secrets.SystemRandom = secrets.SystemRandom()

    def execute(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Executes a callable with exponential-backoff retry.

        An exception is retried iff it is a subclass of
        ``retryable_exceptions`` AND not a subclass of
        ``non_retryable_exceptions``. This lets callers exclude
        programmer errors (TypeError, ValueError, KeyError,
        AttributeError, NameError, IndexError) from the default
        retry set while still allowing them to opt in by listing
        them in ``retryable_exceptions``.

        Args:
            fn: The callable to execute.
            *args: Positional arguments for *fn*.
            **kwargs: Keyword arguments for *fn*.

        Returns:
            The return value of *fn*.

        Raises:
            Exception: The last exception encountered if all retries are exhausted.
        """
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except BaseException as exc:
                if not isinstance(exc, self.retryable_exceptions):
                    raise
                if isinstance(exc, self.non_retryable_exceptions) and not any(
                    issubclass(t, type(exc)) for t in self.retryable_exceptions
                ):
                    raise
                last_exc = exc
                if attempt < self.max_retries:
                    jitter = self.rng.uniform(0, 0.05)
                    delay = min(self.base_delay * (2**attempt) + jitter, self.max_delay)
                    time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("unexpected: no exception captured in retry loop")


class Breaker:
    """Per-subscriber circuit breaker that stops dispatching to failing subscribers.

    Transitions: CLOSED -> OPEN (after *failure_threshold* consecutive failures)
                 OPEN -> HALF_OPEN (after *cooldown_seconds*)
                 HALF_OPEN -> CLOSED (on success) or -> OPEN (on failure)
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60.0) -> None:
        self.threshold: int = failure_threshold
        self.cooldown: float = cooldown_seconds
        self.lock: threading.Lock = threading.Lock()
        self.failures: dict[str, int] = {}
        self.subscriber_state: dict[str, str] = {}
        self.opened_at: dict[str, float] = {}

    def allow_request(self, subscriber_id: str) -> bool:
        """Returns True if the request should be allowed through."""
        with self.lock:
            state = self.subscriber_state.get(subscriber_id, self.CLOSED)
            if state == self.CLOSED:
                return True
            if state == self.OPEN:
                opened = self.opened_at.get(subscriber_id, 0.0)
                if time.monotonic() - opened >= self.cooldown:
                    self.subscriber_state[subscriber_id] = self.HALF_OPEN
                    return True
                return False
            return True  # HALF_OPEN — allow probe request

    def record_failure(self, subscriber_id: str) -> None:
        """Records a failure for the subscriber. May trip circuit to OPEN."""
        with self.lock:
            if len(self.failures) >= 100000 and subscriber_id not in self.failures:
                return
            count = self.failures.get(subscriber_id, 0) + 1
            self.failures[subscriber_id] = count
            if count >= self.threshold:
                self.subscriber_state[subscriber_id] = self.OPEN
                self.opened_at[subscriber_id] = time.monotonic()

    def record_success(self, subscriber_id: str) -> None:
        """Resets failure count and closes the circuit."""
        with self.lock:
            self.failures.pop(subscriber_id, None)
            prev = self.subscriber_state.pop(subscriber_id, None)
            self.opened_at.pop(subscriber_id, None)
            if prev == self.HALF_OPEN:
                logger.info("circuit breaker closed for subscriber {}", subscriber_id)

    def state(self, subscriber_id: str) -> str:
        """Returns the current circuit state for the subscriber."""
        with self.lock:
            return self.subscriber_state.get(subscriber_id, self.CLOSED)

    def cleanup(self) -> None:
        now = time.monotonic()
        stale_sids: list[str] = []
        with self.lock:
            for sid, state in self.subscriber_state.items():
                if state == "closed" and sid not in self.failures:
                    stale_sids.append(sid)
                elif state == "open" and sid in self.opened_at:
                    if now - self.opened_at[sid] > 3600:
                        stale_sids.append(sid)
            for sid in stale_sids:
                self.failures.pop(sid, None)
                self.subscriber_state.pop(sid, None)
                self.opened_at.pop(sid, None)
