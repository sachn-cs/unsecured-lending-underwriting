"""Multi-signature wallet support for Algorand settlements.

Item 49 from production roadmap.
"""

from __future__ import annotations

from typing import Any


class MultiSigWallet:
    """Represents an M-of-N multisig wallet on Algorand.

    In production this should integrate with py-algorand-sdk's
    `algosdk.multisig` module for actual transaction signing.
    """

    def __init__(self, version: int, threshold: int, addresses: list[str]) -> None:
        if version < 1:
            raise ValueError("version must be >= 1")
        if threshold <= 0 or threshold > len(addresses):
            raise ValueError("threshold must be > 0 and <= number of addresses")
        if len(addresses) < 2:
            raise ValueError("multisig requires at least 2 addresses")
        self.version = version
        self.threshold = threshold
        self.addresses = list(addresses)

    def to_dict(self) -> dict[str, Any]:
        """Returns serializable wallet metadata."""
        return {
            "version": self.version,
            "threshold": self.threshold,
            "addresses": self.addresses,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MultiSigWallet:
        return cls(
            version=payload["version"],
            threshold=payload["threshold"],
            addresses=payload["addresses"],
        )

    def is_valid_signature_count(self, sig_count: int) -> bool:
        """Returns True if signature count meets threshold."""
        return sig_count >= self.threshold

    def add_address(self, address: str) -> None:
        """Adds a new signer address."""
        if address not in self.addresses:
            self.addresses.append(address)

    def remove_address(self, address: str) -> bool:
        """Removes a signer address if it exists."""
        if address in self.addresses:
            self.addresses.remove(address)
            return True
        return False
