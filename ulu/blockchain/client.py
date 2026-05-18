"""Async Algorand client wrapper."""

from __future__ import annotations

from algosdk.error import AlgodHTTPError
from algosdk.v2client.algod import AlgodClient


class BlockchainConnectionError(Exception):
    """Raised when the Algorand node is unreachable or returns an error."""


class AlgorandClient:
    """Lightweight async wrapper around AlgodClient for settlement anchoring."""

    def __init__(self, algod_url: str, algod_token: str) -> None:
        self.algod_url = algod_url
        self.algod_token = algod_token
        self.client = AlgodClient(self.algod_token, self.algod_url)

    def health(self) -> dict:
        """Returns node status for health checks."""
        try:
            return self.client.status()
        except (ConnectionError, TimeoutError) as exc:
            raise BlockchainConnectionError(f"Algorand node unreachable: {exc}") from exc
        except AlgodHTTPError as exc:
            raise BlockchainConnectionError(f"Algorand node returned error: {exc}") from exc

    def suggested_params(self) -> dict:
        return self.client.suggested_params()
