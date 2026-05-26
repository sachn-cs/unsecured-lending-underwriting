"""Circuit breaker for resilient store and bus operations.

Tracks failure count and opens the circuit when a threshold is exceeded.
After a cooldown period, transitions to half-open for probation.
"""

from __future__ import annotations

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "RetryPolicy",
]

import logging
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

from underwrite.__exceptions__ import CircuitBreakerOpenError

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit-breaker state: closed, open, or half-open."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker with configurable thresholds."""

    def __init__(self,
                 failure_threshold: int = 5,
                 recovery_timeout: float = 30.0,
                 name: str = "") -> None:
        """Initialises a circuit breaker.

        Args:
            failure_threshold: Consecutive failures before opening.
            recovery_timeout: Seconds before transitioning to half-open.
            name: Optional name for logging / debugging.
        """
        self.__name: str = name
        self.__failure_threshold: int = failure_threshold
        self.__recovery_timeout: float = recovery_timeout
        self.__lock: threading.Lock = threading.Lock()
        self.__state: CircuitState = CircuitState.CLOSED
        self.__failure_count: int = 0
        self.__last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        """Returns the current circuit state, potentially transitioning to half-open."""
        return self.__get_state()

    @property
    def failure_count(self) -> int:
        """Returns the consecutive failure count."""
        with self.__lock:
            return self.__failure_count

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
        state = self.__get_state()
        if state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(f"circuit {self.__name} is open")

        try:
            result = fn(*args, **kwargs)
            self.__on_success()
            return result
        except Exception:
            self.__on_failure()
            raise

    def __get_state(self) -> CircuitState:
        with self.__lock:
            if self.__state == CircuitState.OPEN:
                if time.monotonic(
                ) - self.__last_failure_time >= self.__recovery_timeout:
                    self.__state = CircuitState.HALF_OPEN
                    logger.info("circuit %s half-open (recovery timeout elapsed)",
                                self.__name)
            return self.__state

    def __on_success(self) -> None:
        with self.__lock:
            prev = self.__state
            self.__failure_count = 0
            self.__state = CircuitState.CLOSED
        if prev != CircuitState.CLOSED:
            logger.info("circuit %s recovered (%s -> closed)", self.__name, prev.value)

    def __on_failure(self) -> None:
        tripped = False
        with self.__lock:
            self.__failure_count += 1
            self.__last_failure_time = time.monotonic()
            if self.__failure_count >= self.__failure_threshold:
                if self.__state != CircuitState.OPEN:
                    tripped = True
                self.__state = CircuitState.OPEN
        if tripped:
            logger.warning("circuit %s tripped open (%d failures)", self.__name,
                           self.__failure_threshold)


class RetryPolicy:
    """Exponential backoff retry with jitter.

    Only exceptions matching *retryable_exceptions* trigger a retry.
    All others are re-raised immediately.
    """

    def __init__(self,
                 max_retries: int = 3,
                 base_delay: float = 0.1,
                 max_delay: float = 5.0,
                 retryable_exceptions: tuple[type[Exception],
                                             ...] | None = None) -> None:
        """Initialises a retry policy with exponential backoff.

        Args:
            max_retries: Maximum retry attempts (not counting the initial call).
            base_delay: Initial delay in seconds (doubled each retry).
            max_delay: Maximum delay cap in seconds.
            retryable_exceptions: Exception types that trigger retry.
                Defaults to ``(Exception,)`` (all exceptions).
        """
        self.__max_retries: int = max_retries
        self.__base_delay: float = base_delay
        self.__max_delay: float = max_delay
        self.__retryable_exceptions: tuple[type[Exception],
                                           ...] = retryable_exceptions or (
                                               Exception,)

    def execute(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Executes a callable with exponential-backoff retry.

        Args:
            fn: The callable to execute.
            *args: Positional arguments for *fn*.
            **kwargs: Keyword arguments for *fn*.

        Returns:
            The return value of *fn*.

        Raises:
            Exception: The last exception encountered if all retries are exhausted.
        """
        import random
        last_exc: Exception | None = None
        for attempt in range(self.__max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except self.__retryable_exceptions as exc:
                last_exc = exc
                if attempt < self.__max_retries:
                    delay = min(
                        self.__base_delay * (2**attempt) +
                        random.random() * 0.1, self.__max_delay)
                    time.sleep(delay)
            except Exception:
                raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("unexpected: no exception captured in retry loop")
