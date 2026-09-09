# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for the BoundedExecutor wrapper used by Core services."""

from __future__ import annotations

import threading
import time

import pytest

from underwrite.services.base import BoundedExecutor, MAX_EXECUTOR_QUEUE_FACTOR


class TestBoundedExecutor:
    def test_constructor_rejects_invalid_workers(self) -> None:
        with pytest.raises(ValueError):
            BoundedExecutor(max_workers=0)

    def test_queue_depth_is_public(self) -> None:
        """The wrapper must expose queue_depth without reaching into private state."""
        executor = BoundedExecutor(max_workers=2)
        try:
            assert executor.queue_depth == 0
            barrier = threading.Event()

            def slow() -> None:
                barrier.wait(timeout=1.0)

            for _ in range(4):
                executor.submit(slow)
            time.sleep(0.05)
            # Two workers can claim two tasks; the remaining two are pending.
            assert executor.queue_depth == 2
            barrier.set()
        finally:
            executor.shutdown()

    def test_is_overloaded_triggers_backpressure(self) -> None:
        executor = BoundedExecutor(max_workers=1, max_queue_factor=2)
        try:
            barrier = threading.Event()
            started = threading.Event()

            def slow() -> None:
                started.set()
                barrier.wait(timeout=1.0)

            executor.submit(slow)
            started.wait(timeout=1.0)
            # One worker is busy; queue up enough tasks to exceed the
            # max_workers * max_queue_factor threshold.
            executor.submit(slow)
            executor.submit(slow)
            executor.submit(slow)
            time.sleep(0.05)
            assert executor.is_overloaded is True
            barrier.set()
        finally:
            executor.shutdown()

    def test_submit_after_shutdown_raises(self) -> None:
        executor = BoundedExecutor(max_workers=1)
        executor.shutdown()
        with pytest.raises(RuntimeError):
            executor.submit(lambda: None)

    def test_no_private_attribute_access(self) -> None:
        """The wrapper must not expose the executor's _work_queue."""
        executor = BoundedExecutor(max_workers=2)
        try:
            assert not hasattr(executor, "_work_queue")
            assert executor.queue_depth >= 0
        finally:
            executor.shutdown()