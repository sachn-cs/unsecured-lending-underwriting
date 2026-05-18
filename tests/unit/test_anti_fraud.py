"""Unit tests for anti-fraud and auction modules."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ulu.anti_fraud.auctions import DelegationAuction
from ulu.anti_fraud.device_fingerprint import DeviceFingerprintService
from ulu.anti_fraud.graph_analysis import GraphAnomalyDetector


class TestDeviceFingerprintService:
    def test_record_and_retrieve(self) -> None:
        svc = DeviceFingerprintService()
        fp = svc.record(
            borrower_id="b1",
            device_id="d1",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            timestamp="2026-05-18T10:00:00Z",
        )
        assert fp.borrower_id == "b1"
        assert fp.device_id == "d1"
        history = svc.get_history("b1")
        assert len(history) == 1

    def test_is_new_device_true(self) -> None:
        svc = DeviceFingerprintService()
        svc.record("b1", "d1", "1.1.1.1", "ua", "2026-05-18T10:00:00Z")
        assert svc.is_new_device("b1", "d2") is True

    def test_is_new_device_false(self) -> None:
        svc = DeviceFingerprintService()
        svc.record("b1", "d1", "1.1.1.1", "ua", "2026-05-18T10:00:00Z")
        assert svc.is_new_device("b1", "d1") is False

    def test_suspicious_location_change_no_history(self) -> None:
        svc = DeviceFingerprintService()
        assert svc.is_suspicious_location_change("b1", "geohash1") is False

    def test_suspicious_location_change_below_min_history(self) -> None:
        svc = DeviceFingerprintService()
        svc.record("b1", "d1", "1.1.1.1", "ua", "2026-05-18T10:00:00Z", geo_hash="abcd")
        assert svc.is_suspicious_location_change("b1", "wxyz") is False

    def test_suspicious_location_change_detected(self) -> None:
        svc = DeviceFingerprintService()
        svc.record("b1", "d1", "1.1.1.1", "ua", "2026-05-18T10:00:00Z", geo_hash="abcd")
        svc.record("b1", "d2", "1.1.1.2", "ua", "2026-05-18T11:00:00Z", geo_hash="abcd")
        assert svc.is_suspicious_location_change("b1", "wxyz") is True

    def test_suspicious_location_change_not_detected_for_empty_geo(self) -> None:
        svc = DeviceFingerprintService()
        svc.record("b1", "d1", "1.1.1.1", "ua", "2026-05-18T10:00:00Z", geo_hash="abcd")
        svc.record("b1", "d2", "1.1.1.2", "ua", "2026-05-18T11:00:00Z", geo_hash="abcd")
        assert svc.is_suspicious_location_change("b1", "") is False

    def test_detect_anomalies_new_device(self) -> None:
        svc = DeviceFingerprintService()
        svc.record("b1", "d1", "1.1.1.1", "ua", "2026-05-18T10:00:00Z")
        result = svc.detect_anomalies("b1", "d2", "1.1.1.2")
        assert result["new_device"] is True
        assert any(a["type"] == "new_device" for a in result["anomalies"])

    def test_detect_anomalies_many_devices(self) -> None:
        svc = DeviceFingerprintService()
        for i in range(6):
            svc.record("b1", f"d{i}", f"1.1.1.{i}", "ua", f"2026-05-18T1{i}:00:00Z")
        result = svc.detect_anomalies("b1", "d6", "1.1.1.6")
        assert any(a["type"] == "many_devices" and a["severity"] == "high" for a in result["anomalies"])

    def test_detect_anomalies_no_anomaly(self) -> None:
        svc = DeviceFingerprintService()
        svc.record("b1", "d1", "1.1.1.1", "ua", "2026-05-18T10:00:00Z")
        result = svc.detect_anomalies("b1", "d1", "1.1.1.1")
        assert result["anomalies"] == []
        assert result["unique_devices"] == 1


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
