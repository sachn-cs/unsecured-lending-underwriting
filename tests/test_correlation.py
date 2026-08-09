"""Tests for the shared correlation context in :mod:`underwrite.__correlation__`.

Covers the public surface: the default (unset) correlation id, explicit
set/get behaviour, and per-thread isolation.
"""

from __future__ import annotations

import threading

from underwrite.__correlation__ import correlation_context, get_log_correlation_id


class TestCorrelationContext:
    def test_unset_returns_empty_string(self) -> None:
        token = correlation_context.set("temporary")
        correlation_context.reset(token)
        assert get_log_correlation_id() == ""

    def test_set_and_get_round_trip(self) -> None:
        token = correlation_context.set("corr-123")
        try:
            assert get_log_correlation_id() == "corr-123"
        finally:
            correlation_context.reset(token)

    def test_reset_restores_previous_value(self) -> None:
        outer = correlation_context.set("outer")
        try:
            inner = correlation_context.set("inner")
            try:
                assert get_log_correlation_id() == "inner"
            finally:
                correlation_context.reset(inner)
            assert get_log_correlation_id() == "outer"
        finally:
            correlation_context.reset(outer)

    def test_restore_to_unset_yields_empty_string(self) -> None:
        token = correlation_context.set("value")
        correlation_context.reset(token)
        assert get_log_correlation_id() == ""

    def test_values_are_isolated_per_thread(self) -> None:
        results: list[str] = []
        barrier = threading.Barrier(2)

        def worker(value: str) -> None:
            correlation_context.set(value)
            barrier.wait()
            results.append(get_log_correlation_id())

        threads = [threading.Thread(target=worker, args=(f"thread-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(results) == ["thread-0", "thread-1"]
