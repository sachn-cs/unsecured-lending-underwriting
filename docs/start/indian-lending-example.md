# Indian lending example

The complete `indian_lending.py` script — the same script referenced
by the [quickstart](quickstart.md) page, with line-by-line context.
Read this alongside the [Indian lending lifecycle](../understand/lifecycle.md)
page for a full picture of what runs underneath.

## The script

```python
--8<-- "examples/indian_lending.py"
```

(The script is rendered inline above via Material for MkDocs'
snippet include; the original lives at
[`docs/start/examples/indian_lending.py`](https://github.com/sachncs/underwrite/blob/master/docs/start/examples/indian_lending.py).)

## Stage-by-stage explanation

The script exercises the full Indian underwriting journey against an
in-memory runtime. Each `runtime.publish` call drives one stage of
the lifecycle described in the [lifecycle page](../understand/lifecycle.md):

| Line | Stage | Service | Event emitted |
|------|-------|---------|---------------|
| 1 | (setup) | — | import underwrite.runtime |
| 2 | Bank seeds capital | `mechanism` | `seed.added` |
| 3 | Borrower onboarded | `mechanism` | `user.added` |
| 4 | DPDPA consent recorded | `consent` | `consent.recorded` |
| 5 | KYC + AML check | `compliance` | `kyc.verified`, `aml.cleared` |
| 6 | CIBIL pull | `credit_bureau` | `credit_bureau.checked` |
| 7 | Pricing under RBI caps | `pricing` | `pricing.computed` |
| 8 | Key Fact Statement | `kfs` | `kfs.generated` |
| 9 | Origination | `mechanism` | `loan.originated` |
| 10 | Health snapshot | (runtime) | — |
| 11 | DLQ snapshot | (bus) | — |

Every event flows through `audit`, which persists a PII-redacted
copy of the event to the in-memory store.

## Running it

```bash
git clone https://github.com/sachncs/underwrite.git
cd underwrite
./setup.sh
source .venv/bin/activate

# Run the demo
python docs/start/examples/indian_lending.py

# Or from inside the docs directory
cd docs/start/examples
python indian_lending.py
```

The script does not require any external services. It uses the
default in-memory store and the in-process event bus, so it
completes in a fraction of a second.

## Expected output

```
seed.added           hdfc-bank seeded ₹10,000,000
user.added           priya-sharma sponsored by hdfc-bank (₹500,000)
consent.recorded     kyc_verification consent granted
kyc.verified         PAN + Aadhaar valid
aml.cleared          Risk score 1 — cleared
ckyc.verify           Registry lookup initiated
credit_bureau.checked Score: 720 (CIBIL)
pricing.computed     ₹300K @ 28% APR, EMI ₹16,543/month
kfs.generated        Key Fact Statement v1.0 issued
loan.originated      ₹300,000 personal loan approved
```

## What the script demonstrates

- **Composition through events.** No service imports another
  service; every interaction goes through the bus.
- **Default-deny authz.** The runtime identity is trusted at
  startup; services trust their own keys when constructed.
- **Ed25519 signatures.** Every event carries a signature; the
  audit service verifies each one.
- **PII redaction.** PAN, Aadhaar, and other token-matched
  identifiers are redacted before persistence.
- **Bounded DLQ.** The DLQ count at the end of the script is 0
  — every event was handled successfully.

## See also

- [Quickstart](quickstart.md) — the install + run walkthrough.
- [Indian lending lifecycle](../understand/lifecycle.md) — the twelve-stage flow.
- [Build your first service](first-service.md) — write a custom service in 50 lines.