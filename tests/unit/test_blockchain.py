"""Unit tests for blockchain modules."""

from __future__ import annotations

from ulu.blockchain.anchoring import AuditLogAnchor, MerkleTree
from ulu.blockchain.tokenization import LoanTokenizationService


class TestMerkleTree:
    def test_empty_tree(self) -> None:
        tree = MerkleTree([])
        assert tree.root is None

    def test_single_leaf(self) -> None:
        tree = MerkleTree(["a"])
        assert tree.root is not None
        assert len(tree.root) == 64

    def test_even_leaves(self) -> None:
        tree = MerkleTree(["a", "b"])
        assert tree.root is not None

    def test_odd_leaves(self) -> None:
        tree = MerkleTree(["a", "b", "c"])
        assert tree.root is not None


class TestLoanTokenizationService:
    def test_derive_asset_name(self) -> None:
        svc = LoanTokenizationService()
        name = svc.derive_asset_name("loan-123")
        assert name.startswith("LOAN-")
        assert len(name) == 13

    def test_prepare_mint_params(self) -> None:
        svc = LoanTokenizationService()
        params = svc.prepare_mint_params("loan-123", 1000.0, 1.0)
        assert params["total"] == 1
        assert params["decimals"] == 0
        assert params["metadata"]["principal"] == 1000.0


class TestAuditLogAnchor:
    def test_anchor(self) -> None:
        anchor = AuditLogAnchor()
        payload = anchor.anchor("abc123")
        assert payload["status"] == "prepared"
        import base64

        note = base64.b64decode(payload["note"]).decode("utf-8")
        assert "ULU_ANCHOR:abc123" in note
