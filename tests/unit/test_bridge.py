"""Unit tests for cross-chain bridge."""

from __future__ import annotations

import pytest

from ulu.blockchain.bridge import BridgeDirection, CrossChainBridge


class TestCrossChainBridge:
    def test_lock_and_mint(self) -> None:
        bridge = CrossChainBridge()
        t = bridge.lock_and_mint("T1", "LOAN-1", 1000.0, BridgeDirection.ALGORAND_TO_ETHEREUM, "addr1", "addr2")
        assert t.transfer_id == "T1"
        assert t.status == "pending"
        assert t.direction == BridgeDirection.ALGORAND_TO_ETHEREUM

    def test_duplicate_raises(self) -> None:
        bridge = CrossChainBridge()
        bridge.lock_and_mint("T1", "LOAN-1", 1000.0, BridgeDirection.ALGORAND_TO_ETHEREUM, "a", "b")
        with pytest.raises(ValueError, match="already exists"):
            bridge.lock_and_mint("T1", "LOAN-1", 1000.0, BridgeDirection.ALGORAND_TO_ETHEREUM, "a", "b")

    def test_confirm_and_complete(self) -> None:
        bridge = CrossChainBridge()
        bridge.lock_and_mint("T1", "LOAN-1", 1000.0, BridgeDirection.ALGORAND_TO_ETHEREUM, "a", "b")
        bridge.confirm("T1")
        t = bridge.complete("T1")
        assert t.status == "completed"
        assert t.completed_at is not None

    def test_confirm_wrong_status_raises(self) -> None:
        bridge = CrossChainBridge()
        bridge.lock_and_mint("T1", "LOAN-1", 1000.0, BridgeDirection.ALGORAND_TO_ETHEREUM, "a", "b")
        bridge.confirm("T1")
        with pytest.raises(ValueError, match="only pending"):
            bridge.confirm("T1")

    def test_fail(self) -> None:
        bridge = CrossChainBridge()
        bridge.lock_and_mint("T1", "LOAN-1", 1000.0, BridgeDirection.ALGORAND_TO_ETHEREUM, "a", "b")
        t = bridge.fail("T1", "timeout")
        assert t.status == "failed"

    def test_get_and_list(self) -> None:
        bridge = CrossChainBridge()
        bridge.lock_and_mint("T1", "LOAN-1", 1000.0, BridgeDirection.ALGORAND_TO_ETHEREUM, "a", "b")
        bridge.lock_and_mint("T2", "LOAN-2", 500.0, BridgeDirection.ETHEREUM_TO_ALGORAND, "c", "d")
        assert bridge.get("T1") is not None
        assert bridge.get("T99") is None
        assert len(bridge.list_by_status("pending")) == 2
