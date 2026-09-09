# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sachin

"""Tests for LocalBus.dispatch deduplication and config data_dir safety."""

from __future__ import annotations

import inspect

import pytest

from underwrite.config import Configuration
from underwrite.local import LocalBus
from underwrite.message import Message


class TestLocalBusDispatchDedup:
    def test_dispatch_delegates_to_dispatch_sync(self) -> None:
        """`dispatch` and `dispatch_sync` must share the same body so that
        future divergence is caught at code review."""
        source = inspect.getsource(LocalBus.dispatch)
        # dispatch() should not duplicate the try/except — it should
        # delegate to dispatch_sync.
        assert "self.dispatch_sync" in source

    def test_dispatch_runs_handler(self) -> None:
        bus = LocalBus()
        captured: list[Message] = []

        def handler(event: Message) -> None:
            captured.append(event)

        bus.subscribe("test.event", handler)
        msg = Message(event_type="test.event", source="t", payload={"x": 1})
        bus.dispatch(handler, msg, "sub-1")
        assert len(captured) == 1
        assert captured[0].event_type == "test.event"

    def test_dispatch_sync_records_failure_in_dlq(self) -> None:
        bus = LocalBus()
        msg = Message(event_type="test.boom", source="t", payload={})

        def fail(_event: Message) -> None:
            raise RuntimeError("boom")

        bus.dispatch_sync(fail, msg, "sub-1")
        assert bus.dlq.count == 1


class TestDataDirValidator:
    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/bin",
            "/bin/sh",
            "/boot",
            "/dev/null",
            "/etc",
            "/etc/passwd",
            "/home/user",
            "/lib",
            "/lib64",
            "/media",
            "/mnt",
            "/opt/something",
            "/proc",
            "/root",
            "/run",
            "/sbin",
            "/srv",
            "/sys",
            "/tmp",
            "/usr",
            "/usr/local",
            "/var",
            "/var/log",
        ],
    )
    def test_rejects_sensitive_system_paths(self, path: str) -> None:
        with pytest.raises(ValueError):
            Configuration(data_dir=path)

    @pytest.mark.parametrize(
        "path",
        [
            "/var/lib/underwrite",
            "/home/underwrite/data",
            "/srv/underwrite",
            "/srv/anything",
            "/opt/data/underwrite",
        ],
    )
    def test_rejects_sensitive_subpaths(self, path: str) -> None:
        """Sub-paths of a sensitive directory inherit the block. Mounting
        /srv/foo for data still touches /srv which the OS expects to
        own."""
        with pytest.raises(ValueError):
            Configuration(data_dir=path)

    @pytest.mark.parametrize("path", ["../escape", "../../etc", "a/../b", "a/b/../../etc"])
    def test_rejects_parent_traversal(self, path: str) -> None:
        with pytest.raises(ValueError):
            Configuration(data_dir=path)

    def test_rejects_empty_and_null_byte(self) -> None:
        with pytest.raises(ValueError):
            Configuration(data_dir="")
        with pytest.raises(ValueError):
            Configuration(data_dir="/var/null\x00byte")

    @pytest.mark.parametrize(
        "path",
        ["./data", "data/underwrite", "/data", "/workspace/underwrite"],
    )
    def test_accepts_safe_paths(self, path: str) -> None:
        config = Configuration(data_dir=path)
        assert config.data_dir == path
