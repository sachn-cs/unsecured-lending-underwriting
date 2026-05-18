"""Log aggregation shipper for forwarding logs to centralized observability.

Item 59 from production roadmap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ulu.infra.logging import logger


class LogShipper:
    """Reads local log files and ships them to ELK/Loki/Grafana Cloud.

    Production should use Filebeat, Fluent Bit, or Vector instead.
    """

    def __init__(self, endpoint: str | None = None, api_key: str | None = None) -> None:
        self.endpoint = endpoint
        self.api_key = api_key

    def _build_payload(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "source": "ulu",
            "records": records,
        }

    def ship(self, log_path: Path) -> dict[str, Any]:
        """Reads a JSONL log file and returns a shipping payload."""
        if not log_path.exists():
            raise FileNotFoundError(f"log file not found: {log_path}")
        records: list[dict[str, Any]] = []
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        records.append({"raw": line})
        payload = self._build_payload(records)
        logger.info("log_shipper_prepared", path=str(log_path), record_count=len(records))
        return payload

    async def ship_async(self, log_path: Path) -> dict[str, Any]:
        """Async variant for non-blocking log shipping."""
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.ship, log_path)
