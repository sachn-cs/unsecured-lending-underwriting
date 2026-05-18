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
