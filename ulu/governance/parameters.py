"""On-chain parameter management for protocol governance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProtocolParameters:
    """Tunable protocol parameters subject to governance votes."""

    max_delegation_rate: float = 0.1
    rate_cap: float = 0.5
    utilization_curve: str = "linear"
    seed_eligibility_threshold: float = 10000.0

    def to_dict(self) -> dict:
        return {
            "max_delegation_rate": self.max_delegation_rate,
            "rate_cap": self.rate_cap,
            "utilization_curve": self.utilization_curve,
            "seed_eligibility_threshold": self.seed_eligibility_threshold,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> ProtocolParameters:
        required_keys = ("max_delegation_rate", "rate_cap", "utilization_curve", "seed_eligibility_threshold")
        missing = [k for k in required_keys if k not in payload]
        if missing:
            raise ValueError(f"missing protocol parameter keys: {missing}")
        return cls(
            max_delegation_rate=payload["max_delegation_rate"],
            rate_cap=payload["rate_cap"],
            utilization_curve=payload["utilization_curve"],
            seed_eligibility_threshold=payload["seed_eligibility_threshold"],
        )
