# Quickstart — Indian Lending in 5 Minutes

This walkthrough simulates a retail loan origination workflow compliant with RBI Digital Lending Guidelines and DPDPA 2023.

## 1. Clone and Setup

```bash
git clone <repo-url>
cd underwrite
./setup.sh
source .venv/bin/activate
```

## 2. Create Config

```bash
underwrite init
```

Edit `underwrite.json` to enable the services needed for an Indian lending flow:

```json
{
  "services": {
    "mechanism":  {"enabled": true},
    "audit":      {"enabled": true},
    "risk":       {"enabled": true},
    "fraud":      {"enabled": true},
    "compliance": {"enabled": true},
    "consent":    {"enabled": true},
    "credit_bureau": {"enabled": true},
    "kfs":        {"enabled": true},
    "pricing":    {"enabled": true},
    "origination": {"enabled": true},
    "underwriter":{"enabled": true},
    "decision":   {"enabled": true}
  }
}
```

## 3. Run Tests

```bash
make test
# 1276 tests pass (KYC validation, RBI caps, AML, CKYC, DPDPA consent)
```

## 4. Start Indian Lending Services

```bash
# Terminal 1 — core state machine
underwrite run mechanism

# Terminal 2 — compliance (KYC/AML)
underwrite run compliance

# Terminal 3 — pricing (RBI caps), credit bureau, KFS
underwrite run pricing credit_bureau kfs

# Terminal 4 — consent, origination, decision
underwrite run consent origination underwriter decision

# Terminal 5 — audit (event ledger + PII redaction)
underwrite run audit
```

## 5. Simulate an Indian Borrower Lifecycle

Run this Python script to simulate a full lending flow:

```python
from underwrite.cli import load_config
from underwrite.runtime import Runtime

config = load_config()
with Runtime(config) as rt:
    rt.start(
        [
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
    )

    # Step 1: Bank seeds capital
    rt.publish(
        "mechanism",
        {
            "command": "add_seed",
            "user": "hdfc-bank",
            "base_budget": 10_000_000.0,
        },
    )

    # Step 2: Add borrower with PAN + Aadhaar
    rt.publish(
        "mechanism",
        {
            "command": "add_user",
            "sponsor": "hdfc-bank",
            "user": "priya-sharma",
            "delegation_amount": 500000.0,
        },
    )

    # Step 3: Record DPDPA consent for KYC
    rt.publish(
        "consent",
        {
            "command": "record",
            "user": "priya-sharma",
            "purpose": "kyc_verification",
        },
    )

    # Step 4: Initiate KYC + AML check
    # Compliance service validates PAN format + category,
    # Aadhaar Verhoeff checksum, AML risk scoring, CKYC trigger
    rt.publish(
        "compliance",
        {
            "command": "kyc_check",
            "user": "priya-sharma",
            "pan": "ABCDE1234F",
            "aadhaar": "123456789012",  # Verhoeff-valid
        },
    )

    # Step 5: Request credit bureau check (CIBIL + CKYC)
    rt.publish(
        "credit_bureau",
        {
            "command": "check",
            "user": "priya-sharma",
            "pan": "ABCDE1234F",
        },
    )

    # Step 6: Request pricing (RBI rate caps applied)
    rt.publish(
        "pricing",
        {
            "command": "compute",
            "user": "priya-sharma",
            "loan_type": "personal",
            "principal": 300000.0,
            "tenure_months": 24,
            "credit_score": 720,
            "monthly_income": 80000.0,
        },
    )
    # Pricing emits pricing.computed with:
    #   annual_rate: 0.28 (capped)
    #   apr: 0.289 (incl. fees, GST)
    #   emi: 16543.20
    #   total_interest: 97036.80
    #   processing_fee: 3000.0
    #   gst_on_fees: 540.0
    #   all_in_cost: 400576.80

    # Step 7: Generate KFS (Key Fact Statement)
    rt.publish(
        "kfs",
        {
            "command": "generate",
            "user": "priya-sharma",
            "loan_type": "personal",
            "principal": 300000.0,
        },
    )

    # Step 8: Originate loan
    rt.publish(
        "mechanism",
        {
            "command": "originate",
            "user": "priya-sharma",
            "principal": 300000.0,
            "term": 24,
            "default_probability": 0.12,
            "protocol_rate": 0.28,
            "max_delegation_rate": 0.05,
        },
    )

    # Step 9: Check health
    print(rt.health())
```

Expected KYC flow:
```
compliance: KYC passed — PAN valid, Aadhaar Verhoeff OK
compliance: AML cleared — risk score 1 (low)
compliance: CKYC verify requested
```

Expected pricing output:
```
pricing: Rate capped at 28.00% (personal loan)
pricing: APR computed at 28.90% (incl. fees + GST)
pricing: EMI = ₹16,543.20 for 24 months
pricing: Total all-in-cost = ₹400,576.80
```

## 6. Check the Audit Trail

```bash
underwrite health
```

View the event sequence in the audit log:

```
seed.added           hdfc-bank seeded ₹10,000,000
user.added           priya-sharma sponsored by hdfc-bank (₹500,000)
consent.recorded     kyc_verification consent granted
kyc.verified         PAN + Aadhaar valid
aml.cleared          Risk score 1 — cleared
ckyc.verify          Registry lookup initiated
credit_bureau.checked Score: 720 (CIBIL)
pricing.computed     ₹300K @ 28% APR, EMI ₹16,543/month
kfs.generated        Key Fact Statement v1.0 issued
loan.originated      ₹300,000 personal loan approved
```

## 7. View the Dead Letter Queue

```bash
underwrite dlq
```

Any failed events (e.g., invalid PAN, Aadhaar checksum failure, consent missing) appear here with the error reason.

## 8. Metrics

```bash
underwrite metrics
```

Shows per-service counters: events handled, KYC processed, loans originated, rate caps enforced.
