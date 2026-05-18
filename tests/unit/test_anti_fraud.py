"""Unit tests for anti-fraud and auction modules."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ulu.anti_fraud.auctions import DelegationAuction
from ulu.anti_fraud.graph_analysis import GraphAnomalyDetector


class TestGraphAnomalyDetector:
    def test_detect_cycles_empty(self) -> None:
        detector = GraphAnomalyDetector()
        cycles = detector.detect_cycles([])
        assert cycles == []

    def test_detect_cycles_found(self) -> None:
        detector = GraphAnomalyDetector()
        edges = [("a", "b"), ("b", "c"), ("c", "a")]
        cycles = detector.detect_cycles(edges)
        assert len(cycles) > 0

    def test_detect_wash_lending(self) -> None:
        detector = GraphAnomalyDetector()
        transactions = [
            {"borrower_id": "b1", "type": "repayment", "timestamp": datetime.now(timezone.utc).isoformat()},
            {"borrower_id": "b1", "type": "origination", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        flagged = detector.detect_wash_lending(transactions, window_hours=24)
        assert len(flagged) == 1
        assert flagged[0]["borrower_id"] == "b1"

    def test_detect_sybil_clusters(self) -> None:
        detector = GraphAnomalyDetector()
        edges = [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")]
        clusters = detector.detect_sybil_clusters(edges, threshold=3, density_threshold=0.3)
        assert len(clusters) == 1
        assert len(clusters[0]) == 5


class TestDelegationAuction:
    def test_place_bid(self) -> None:
        auction = DelegationAuction()
        auction.place_bid("b1", "s1", 0.05)
        assert len(auction.bids) == 1

    def test_negative_bid_rejected(self) -> None:
        auction = DelegationAuction()
        with pytest.raises(ValueError):
            auction.place_bid("b1", "s1", -0.01)

    def test_run_auction(self) -> None:
        auction = DelegationAuction()
        auction.place_bid("b1", "s1", 0.05)
        auction.place_bid("b2", "s2", 0.03)
        result = auction.run_auction(principal=1000.0, term=1.0)
        assert result["winning_rate"] == 0.03

    def test_run_auction_no_bids(self) -> None:
        auction = DelegationAuction()
        with pytest.raises(ValueError):
            auction.run_auction(principal=1000.0, term=1.0)
