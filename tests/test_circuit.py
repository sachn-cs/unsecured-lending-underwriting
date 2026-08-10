# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for CircuitBreaker and RetryPolicy."""

from __future__ import annotations

import traceback

import pytest

from underwrite.circuit import CircuitBreaker, CircuitState, RetryPolicy
from underwrite.exceptions import CircuitBreakerOpenError


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
        assert cb.state == CircuitState.OPEN

    def test_open_raises_circuit_breaker_open_error(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(lambda: "ok")

    def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
        cb.call(lambda: "ok")
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_transitions_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.001)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
        import time

        time.sleep(0.005)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.001)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
        import time

        time.sleep(0.005)
        assert cb.state == CircuitState.HALF_OPEN
        cb.call(lambda: "ok")
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.001)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
        import time

        time.sleep(0.005)
        assert cb.state == CircuitState.HALF_OPEN
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("again")))
        assert cb.state == CircuitState.OPEN


class TestRetryPolicy:
    def test_success_on_first_attempt(self) -> None:
        rp = RetryPolicy(max_retries=2)
        result = rp.execute(lambda: "ok")
        assert result == "ok"

    def test_retries_on_failure(self) -> None:
        """ConnectionResetError is treated as transient and retried."""
        rp = RetryPolicy(max_retries=3, base_delay=0.001, retryable_exceptions=(ConnectionResetError,))
        calls: list = []

        def flaky() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionResetError("not yet")
            return "ok"

        result = rp.execute(flaky)
        assert result == "ok"
        assert len(calls) == 3

    def test_exhausts_retries(self) -> None:
        rp = RetryPolicy(max_retries=2, base_delay=0.001, retryable_exceptions=(ConnectionResetError,))
        with pytest.raises(ConnectionResetError):
            rp.execute(lambda: (_ for _ in ()).throw(ConnectionResetError("always")))

    def test_non_retryable_exception_not_retried(self) -> None:
        """TypeError is a programmer error; never retried even when
        the caller did not list it in retryable_exceptions."""
        rp = RetryPolicy(max_retries=3, base_delay=0.001, retryable_exceptions=(ValueError,))
        calls: list = []
        with pytest.raises(TypeError):
            rp.execute(lambda: (_ for _ in ()).throw(TypeError("fatal")))
        assert len(calls) == 0  # never retried

    def test_only_retryable_exceptions_retried(self) -> None:
        rp = RetryPolicy(max_retries=3, base_delay=0.001, retryable_exceptions=(ValueError,))
        calls: list = []

        def flaky() -> str:
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("transient")
            return "ok"

        result = rp.execute(flaky)
        assert result == "ok"
        assert len(calls) == 2

    def test_non_retryable_exception_skips_retries_and_raises(self) -> None:
        rp = RetryPolicy(max_retries=3, base_delay=0.001, retryable_exceptions=(ValueError,))
        with pytest.raises(TypeError):
            rp.execute(lambda: (_ for _ in ()).throw(TypeError("fatal")))

    def test_retryable_exception_tuple_defaults_to_exception(self) -> None:
        rp = RetryPolicy(max_retries=1, base_delay=0.001)
        calls: list = []

        def flaky() -> str:
            calls.append(1)
            raise RuntimeError("any")

        with pytest.raises(RuntimeError):
            rp.execute(flaky)
        assert len(calls) == 2  # retried once

    def test_non_retryable_exception_preserves_traceback(self) -> None:
        rp = RetryPolicy(max_retries=1, base_delay=0.001, retryable_exceptions=(ValueError,))

        def deeply_nested() -> str:
            def inner() -> str:
                raise TypeError("fatal from inner")

            return inner()

        with pytest.raises(TypeError) as exc_info:
            rp.execute(deeply_nested)
        tb = "".join(traceback.format_tb(exc_info.tb))
        assert "deeply_nested" in tb
        assert "inner" in tb
