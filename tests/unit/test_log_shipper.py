"""Unit tests for log aggregation shipper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ulu.infra.log_shipper import LogShipper


class TestLogShipper:
    def test_ship_jsonl(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.log"
        log_file.write_text(
            json.dumps({"level": "info", "msg": "hello"}) + "\n"
            + json.dumps({"level": "error", "msg": "boom"}) + "\n"
        )
        shipper = LogShipper()
        payload = shipper.ship(log_file)
        assert payload["source"] == "ulu"
        assert len(payload["records"]) == 2
        assert payload["records"][0]["msg"] == "hello"

    def test_ship_missing_file_raises(self, tmp_path: Path) -> None:
        shipper = LogShipper()
        with pytest.raises(FileNotFoundError):
            shipper.ship(tmp_path / "missing.log")

    def test_ship_malformed_line(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.log"
        log_file.write_text("not json\n")
        shipper = LogShipper()
        payload = shipper.ship(log_file)
        assert payload["records"][0]["raw"] == "not json"

    @pytest.mark.asyncio
    async def test_ship_async(self, tmp_path: Path) -> None:
        log_file = tmp_path / "app.log"
        log_file.write_text(json.dumps({"a": 1}) + "\n")
        shipper = LogShipper()
        payload = await shipper.ship_async(log_file)
        assert len(payload["records"]) == 1
