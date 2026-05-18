"""ASA tokenization for loan obligations on Algorand."""

from __future__ import annotations

import hashlib


class LoanTokenizationService:
    """Manages ASA minting for individual loan obligations."""

    def __init__(self, client: object | None = None) -> None:
        self.client = client

    def derive_asset_name(self, loan_id: str) -> str:
        """Derives a short ASA name from loan ID hash."""
        digest = hashlib.sha256(loan_id.encode()).hexdigest()
        return f"LOAN-{digest[:8].upper()}"

    def prepare_mint_params(self, loan_id: str, principal: float, term: float) -> dict:
        """Prepares ASA creation parameters (unsigned)."""
        return {
            "asset_name": self.derive_asset_name(loan_id),
            "total": 1,
            "decimals": 0,
            "unit_name": "DEBT",
            "metadata": {
                "loan_id": loan_id,
                "principal": principal,
                "term": term,
            },
        }
