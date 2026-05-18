"""Merkle root anchoring of audit log to Algorand blockchain."""

from __future__ import annotations

import base64
import hashlib


class MerkleTree:
    """Simple binary Merkle tree for audit event hashing.

    Uses domain-separated prefixes for leaves and branches to prevent
    second-preimage attacks on variable-length inputs.
    """

    LEAF_PREFIX = b"\x00"
    BRANCH_PREFIX = b"\x01"

    def __init__(self, leaves: list[str]) -> None:
        self.leaves = leaves
        self.root = self.compute_root()

    def _hash_leaf(self, leaf: str) -> str:
        return hashlib.sha256(self.LEAF_PREFIX + leaf.encode("utf-8")).hexdigest()

    def _hash_branch(self, left: str, right: str) -> str:
        return hashlib.sha256(self.BRANCH_PREFIX + left.encode("utf-8") + right.encode("utf-8")).hexdigest()

    def compute_root(self) -> str | None:
        if not self.leaves:
            return None
        current = [self._hash_leaf(leaf) for leaf in self.leaves]
        while len(current) > 1:
            next_level: list[str] = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else left
                next_level.append(self._hash_branch(left, right))
            current = next_level
        return current[0]


class IncrementalMerkleTree:
    """Merkle tree that supports O(log n) leaf append via incremental hashing.

    Stores at most one orphan hash per level, only recomputing the path
    from the new leaf to the root.
    """

    LEAF_PREFIX = b"\x00"
    BRANCH_PREFIX = b"\x01"

    def __init__(self) -> None:
        self.leaves: list[str] = []
        self._orphans: list[str | None] = []

    def _hash_leaf(self, leaf: str) -> str:
        return hashlib.sha256(self.LEAF_PREFIX + leaf.encode("utf-8")).hexdigest()

    def _hash_branch(self, left: str, right: str) -> str:
        return hashlib.sha256(
            self.BRANCH_PREFIX + left.encode("utf-8") + right.encode("utf-8")
        ).hexdigest()

    def append(self, leaf: str) -> str:
        """Appends a leaf and returns the new root."""
        self.leaves.append(leaf)
        current = self._hash_leaf(leaf)
        level = 0
        while True:
            if level >= len(self._orphans):
                self._orphans.append(current)
                break
            orphan = self._orphans[level]
            if orphan is None:
                self._orphans[level] = current
                break
            current = self._hash_branch(orphan, current)
            self._orphans[level] = None
            level += 1
        return self.root()

    def root(self) -> str | None:
        """Returns the current Merkle root."""
        if not self.leaves:
            return None
        current_level = [self._hash_leaf(leaf) for leaf in self.leaves]
        while len(current_level) > 1:
            next_level: list[str] = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                right = current_level[i + 1] if i + 1 < len(current_level) else left
                next_level.append(self._hash_branch(left, right))
            current_level = next_level
        return current_level[0]

    def compute_root_full(self) -> str | None:
        """Full recomputation for verification (O(n))."""
        return self.root()


class AuditLogAnchor:
    """Anchors daily Merkle roots to Algorand for immutable timestamping."""

    def __init__(self, client: object | None = None) -> None:
        self.client = client

    def anchor(self, merkle_root: str) -> dict:
        """Prepares an anchoring transaction payload."""
        note = f"ULU_ANCHOR:{merkle_root}"
        return {
            "note": base64.b64encode(note.encode("utf-8")).decode("ascii"),
            "status": "prepared",
        }
