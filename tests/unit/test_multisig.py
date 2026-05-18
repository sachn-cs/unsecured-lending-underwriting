"""Unit tests for multi-signature wallet support."""

from __future__ import annotations

import pytest

from ulu.blockchain.multisig import MultiSigWallet


class TestMultiSigWallet:
    def test_create(self) -> None:
        w = MultiSigWallet(1, 2, ["addr1", "addr2", "addr3"])
        assert w.version == 1
        assert w.threshold == 2
        assert len(w.addresses) == 3

    def test_invalid_threshold_zero(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            MultiSigWallet(1, 0, ["a", "b"])

    def test_invalid_threshold_exceeds_addresses(self) -> None:
        with pytest.raises(ValueError, match="threshold"):
            MultiSigWallet(1, 3, ["a", "b"])

    def test_insufficient_addresses(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            MultiSigWallet(1, 1, ["a"])

    def test_signature_count_validation(self) -> None:
        w = MultiSigWallet(1, 2, ["a", "b", "c"])
        assert w.is_valid_signature_count(2) is True
        assert w.is_valid_signature_count(1) is False
        assert w.is_valid_signature_count(3) is True

    def test_round_trip_dict(self) -> None:
        w = MultiSigWallet(1, 2, ["addr1", "addr2"])
        d = w.to_dict()
        restored = MultiSigWallet.from_dict(d)
        assert restored.threshold == w.threshold
        assert restored.addresses == w.addresses

    def test_add_and_remove_address(self) -> None:
        w = MultiSigWallet(1, 2, ["a", "b"])
        w.add_address("c")
        assert "c" in w.addresses
        assert w.remove_address("c") is True
        assert "c" not in w.addresses
        assert w.remove_address("z") is False
