"""Unit tests for Merkle tree anchoring."""

from __future__ import annotations

from ulu.blockchain.anchoring import IncrementalMerkleTree, MerkleTree


class TestMerkleTree:
    def test_empty_root(self) -> None:
        tree = MerkleTree([])
        assert tree.root is None

    def test_single_leaf(self) -> None:
        tree = MerkleTree(["a"])
        assert tree.root is not None

    def test_root_matches_incremental(self) -> None:
        leaves = ["a", "b", "c", "d"]
        tree = MerkleTree(leaves)
        inc = IncrementalMerkleTree()
        for leaf in leaves:
            inc.append(leaf)
        assert inc.root() == tree.root


class TestIncrementalMerkleTree:
    def test_append_single(self) -> None:
        inc = IncrementalMerkleTree()
        root = inc.append("a")
        assert root is not None
        assert len(inc.leaves) == 1

    def test_append_multiple(self) -> None:
        inc = IncrementalMerkleTree()
        for leaf in ["a", "b", "c"]:
            inc.append(leaf)
        assert len(inc.leaves) == 3
        assert inc.root() is not None

    def test_root_matches_full_recomputation(self) -> None:
        inc = IncrementalMerkleTree()
        for leaf in ["x", "y", "z"]:
            inc.append(leaf)
        assert inc.root() == inc.compute_root_full()

    def test_consistency_across_appends(self) -> None:
        inc = IncrementalMerkleTree()
        roots = []
        for leaf in ["a", "b", "c", "d", "e"]:
            roots.append(inc.append(leaf))
        assert all(r is not None for r in roots)
        assert roots[-1] == inc.root()
        assert inc.root() == inc.compute_root_full()

    def test_empty_root(self) -> None:
        inc = IncrementalMerkleTree()
        assert inc.root() is None
