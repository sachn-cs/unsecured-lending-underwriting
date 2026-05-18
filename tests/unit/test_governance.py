"""Unit tests for governance and oracle modules."""

from __future__ import annotations

import pytest

from ulu.governance.oracles import DataFeedOracle
from ulu.governance.parameters import ProtocolParameters
from ulu.governance.voting import GovernanceTally, Vote


class TestProtocolParameters:
    def test_to_dict(self) -> None:
        params = ProtocolParameters(max_delegation_rate=0.15)
        d = params.to_dict()
        assert d["max_delegation_rate"] == 0.15

    def test_from_dict(self) -> None:
        params = ProtocolParameters.from_dict(
            {
                "rate_cap": 0.6,
                "max_delegation_rate": 0.1,
                "utilization_curve": "linear",
                "seed_eligibility_threshold": 10000.0,
            }
        )
        assert params.rate_cap == 0.6

    def test_from_dict_rejects_missing_keys(self) -> None:
        with pytest.raises(ValueError, match="missing protocol parameter keys"):
            ProtocolParameters.from_dict({"rate_cap": 0.6})


class TestGovernanceTally:
    def test_tally_passed(self) -> None:
        tally = GovernanceTally(majority_threshold=0.51)
        tally.cast(Vote(voter_id="v1", proposal_id="p1", weight=60.0, in_favor=True))
        tally.cast(Vote(voter_id="v2", proposal_id="p1", weight=40.0, in_favor=False))
        result = tally.tally("p1")
        assert result["passed"] is True
        assert result["ratio"] == 0.6

    def test_tally_failed(self) -> None:
        tally = GovernanceTally(majority_threshold=0.51)
        tally.cast(Vote(voter_id="v1", proposal_id="p1", weight=40.0, in_favor=True))
        tally.cast(Vote(voter_id="v2", proposal_id="p1", weight=60.0, in_favor=False))
        result = tally.tally("p1")
        assert result["passed"] is False

    def test_tally_no_votes(self) -> None:
        tally = GovernanceTally()
        result = tally.tally("p1")
        assert result["passed"] is False
        assert result["reason"] == "no_votes"

    def test_negative_weight_rejected(self) -> None:
        tally = GovernanceTally()
        with pytest.raises(ValueError):
            tally.cast(Vote(voter_id="v1", proposal_id="p1", weight=-10.0, in_favor=True))

    def test_dedupe_votes(self) -> None:
        tally = GovernanceTally(majority_threshold=0.51)
        tally.cast(Vote(voter_id="v1", proposal_id="p1", weight=60.0, in_favor=True))
        tally.cast(Vote(voter_id="v1", proposal_id="p1", weight=30.0, in_favor=False))
        result = tally.tally("p1")
        assert result["passed"] is False
        assert result["ratio"] == 0.0

    def test_quorum_not_met(self) -> None:
        tally = GovernanceTally(majority_threshold=0.51, min_participation_weight=100.0)
        tally.cast(Vote(voter_id="v1", proposal_id="p1", weight=50.0, in_favor=True))
        result = tally.tally("p1")
        assert result["passed"] is False
        assert result["reason"] == "quorum_not_met"


class TestDataFeedOracle:
    def test_aggregate_median(self) -> None:
        oracle = DataFeedOracle()
        assert oracle.aggregate_median([1.0, 2.0, 3.0, 4.0, 5.0]) == 3.0

    def test_aggregate_median_empty(self) -> None:
        oracle = DataFeedOracle()
        with pytest.raises(ValueError):
            oracle.aggregate_median([])

    def test_sign_attestation(self) -> None:
        oracle = DataFeedOracle(sources=["a", "b"])
        attestation = oracle.sign_attestation("price", 100.0, "2026-01-01T00:00:00")
        assert attestation["aggregated_value"] == 100.0
        assert attestation["source_count"] == 2
