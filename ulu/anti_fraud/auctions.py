"""Delegation capacity auction engine."""

from __future__ import annotations

import heapq


class DelegationAuction:
    """Competitive auction for delegation capacity."""

    def __init__(self) -> None:
        self.bids: list[tuple[float, str, str]] = []

    def place_bid(self, borrower_id: str, sponsor_id: str, rate: float) -> None:
        if rate < 0:
            raise ValueError("bid rate must be non-negative")
        heapq.heappush(self.bids, (rate, borrower_id, sponsor_id))

    def run_auction(self, principal: float, term: float) -> dict:
        if not self.bids:
            raise ValueError("no bids placed")
        winning_rate, borrower_id, sponsor_id = heapq.heappop(self.bids)
        return {
            "borrower_id": borrower_id,
            "sponsor_id": sponsor_id,
            "winning_rate": winning_rate,
            "principal": principal,
            "term": term,
            "delegation_premium": winning_rate * principal * term,
        }
