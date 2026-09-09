"""End-to-end Indian lending lifecycle demo.

Runs a full RBI Digital Lending Guidelines + DPDPA 2023 aligned
origination against a fresh in-memory Underwrite runtime: bank seeds
capital, a borrower is onboarded with PAN + Aadhaar, DPDPA consent is
recorded, KYC/AML passes, a credit-bureau pull happens, pricing is
computed under RBI caps, a Key Fact Statement is issued, and the loan
is originated.

Run it:

    python docs/examples/indian_lending.py

The script does not require any external services. It uses the default
in-memory store and the in-process event bus, so it completes in a
fraction of a second.

The same walkthrough, with commentary, is in ``docs/QUICKSTART.md``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make sure ``import underwrite`` works whether the script is run from
# the repo root or from inside ``docs/examples/``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from underwrite.runtime import Runtime  # noqa: E402

SERVICES = [
    "mechanism",
    "audit",
    "risk",
    "fraud",
    "compliance",
    "consent",
    "credit_bureau",
    "kfs",
    "pricing",
    "origination",
    "underwriter",
    "decision",
]


def _pretty(event: str, payload: dict) -> None:
    """Print a compact event trail for the demo."""
    print(f"  -> {event}: {json.dumps(payload, sort_keys=True)}")


def main() -> int:
    with Runtime() as runtime:
        runtime.start(SERVICES)

        # 1. Bank seeds capital.
        runtime.publish(
            "mechanism",
            {
                "command": "add_seed",
                "user": "hdfc-bank",
                "base_budget": 10_000_000.0,
            },
        )
        _pretty("seed.added", {"bank": "hdfc-bank", "budget": 10_000_000.0})

        # 2. Borrower is onboarded with a delegation budget.
        runtime.publish(
            "mechanism",
            {
                "command": "add_user",
                "sponsor": "hdfc-bank",
                "user": "priya-sharma",
                "delegation_amount": 500_000.0,
            },
        )
        _pretty("user.added", {"user": "priya-sharma", "delegation": 500_000.0})

        # 3. DPDPA consent for KYC processing.
        runtime.publish(
            "consent",
            {
                "command": "record",
                "user": "priya-sharma",
                "purpose": "kyc_verification",
            },
        )
        _pretty("consent.recorded", {"purpose": "kyc_verification"})

        # 4. KYC + AML check (PAN format, Aadhaar Verhoeff, AML risk score).
        runtime.publish(
            "compliance",
            {
                "command": "kyc_check",
                "user": "priya-sharma",
                "pan": "ABCDE1234F",
                "aadhaar": "123456789012",  # 12-digit, Verhoeff-valid in test fixtures.
            },
        )
        _pretty("kyc.verified", {"user": "priya-sharma", "pan": "ABCDE1234F"})

        # 5. CIBIL + CKYC pull.
        runtime.publish(
            "credit_bureau",
            {
                "command": "check",
                "user": "priya-sharma",
                "pan": "ABCDE1234F",
            },
        )
        _pretty("credit_bureau.checked", {"user": "priya-sharma"})

        # 6. Pricing under RBI caps.
        runtime.publish(
            "pricing",
            {
                "command": "compute",
                "user": "priya-sharma",
                "loan_type": "personal",
                "principal": 300_000.0,
                "tenure_months": 24,
                "credit_score": 720,
                "monthly_income": 80_000.0,
            },
        )
        _pretty("pricing.computed", {"loan_type": "personal", "principal": 300_000.0})

        # 7. Key Fact Statement.
        runtime.publish(
            "kfs",
            {
                "command": "generate",
                "user": "priya-sharma",
                "loan_type": "personal",
                "principal": 300_000.0,
            },
        )
        _pretty("kfs.generated", {"loan_type": "personal", "principal": 300_000.0})

        # 8. Originate the loan.
        runtime.publish(
            "mechanism",
            {
                "command": "originate",
                "user": "priya-sharma",
                "principal": 300_000.0,
                "term": 24,
                "default_probability": 0.12,
                "protocol_rate": 0.28,
                "max_delegation_rate": 0.05,
            },
        )
        _pretty("loan.originated", {"user": "priya-sharma", "principal": 300_000.0})

        # 9. Snapshot health and DLQ.
        print()
        print("health:", runtime.health.status())
        print("dlq:", runtime.bus.dlq.count())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())