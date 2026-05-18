"""Off-chain data feed aggregation for on-chain oracle consumption."""

from __future__ import annotations

import statistics


class DataFeedOracle:
    """Aggregates multiple off-chain data sources into a single attestation."""

    def __init__(self, sources: list[str] | None = None) -> None:
        self.sources = sources or []

    def aggregate_median(self, values: list[float]) -> float:
        if not values:
            raise ValueError("no values to aggregate")
        return float(statistics.median(values))

    def sign_attestation(self, key: str, value: float, timestamp: str) -> dict:
        return {
            "source_count": len(self.sources),
            "aggregated_value": value,
            "timestamp": timestamp,
            "key": key,
        }
