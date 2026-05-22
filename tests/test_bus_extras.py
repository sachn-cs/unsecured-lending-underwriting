"""Tests for DeadLetterQueue and RateLimiter."""

from __future__ import annotations

import time

from underwrite.__bus__ import DeadLetterQueue, LocalBus, RateLimiter
from underwrite.__events__ import Event
from underwrite.__exceptions__ import RateLimitError


class TestDeadLetterQueue:

    def test_empty_by_default(self) -> None:
        dlq = DeadLetterQueue()
        assert dlq.count == 0
        assert dlq.records == []

    def test_put_and_count(self) -> None:
        dlq = DeadLetterQueue()
        dlq.put(Event(event_type="t", source="s"), "error", "sub1")
        assert dlq.count == 1

    def test_clear(self) -> None:
        dlq = DeadLetterQueue()
        dlq.put(Event(event_type="t", source="s"), "err", "s1")
        dlq.clear()
        assert dlq.count == 0

    def test_replay(self) -> None:
        bus = LocalBus()
        dlq = DeadLetterQueue()
        dlq.put(Event(event_type="t", source="s", payload={"k": "v"}), "err",
                "s1")
        bus.start()
        n = dlq.replay(bus)
        assert n == 1

    def test_replay_with_max(self) -> None:
        bus = LocalBus()
        dlq = DeadLetterQueue()
        dlq.put(Event(event_type="t1", source="s"), "err", "s1")
        dlq.put(Event(event_type="t2", source="s"), "err", "s1")
        n = dlq.replay(bus, max_count=1)
        assert n == 1
        assert dlq.count == 1

    def test_cap_evicts_oldest(self) -> None:
        dlq = DeadLetterQueue(max_records=3)
        for i in range(5):
            dlq.put(Event(event_type=f"e{i}", source="s"), "err", "s1")
        assert dlq.count == 3
        # oldest two evicted; youngest three remain
        remaining = [r.event.event_type for r in dlq.records]
        assert remaining == ["e2", "e3", "e4"]


class TestRateLimiter:

    def test_allows_first_call(self) -> None:
        rl = RateLimiter(max_rate=10)
        assert rl.check("key") is True

    def test_blocks_excessive_calls(self) -> None:
        rl = RateLimiter(max_rate=1000)
        rl.check("key")
        allowed = [rl.check("key") for _ in range(10)]
        assert not all(allowed)

    def test_assert_allowed_passes(self) -> None:
        rl = RateLimiter(max_rate=10)
        rl.assert_allowed("key")

    def test_assert_allowed_raises(self) -> None:
        rl = RateLimiter(max_rate=1000)
        rl.check("key")
        try:
            rl.assert_allowed("key")
            raise AssertionError("expected RateLimitError")
        except RateLimitError:
            pass

    def test_recovery_after_interval(self) -> None:
        rl = RateLimiter(max_rate=1000000, interval=0.001)
        rl.assert_allowed("k")
        time.sleep(0.002)
        rl.assert_allowed("k")


class TestLocalBusDLQ:

    def test_failed_handler_goes_to_dlq(self) -> None:
        bus = LocalBus()
        bus.subscribe("test.fail", lambda e:
                      (_ for _ in ()).throw(RuntimeError("fail")))
        bus.start()
        bus.publish(Event(event_type="test.fail", source="s"))
        assert bus.dlq.count == 1

    def test_healthy_handler_skips_dlq(self) -> None:
        bus = LocalBus()
        results: list = []
        bus.subscribe("test.ok", lambda e: results.append(1))
        bus.start()
        bus.publish(Event(event_type="test.ok", source="s"))
        assert bus.dlq.count == 0
        assert results == [1]
