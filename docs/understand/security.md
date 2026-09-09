# Security and auditability

The runtime's security posture is **structured around a single
primitive: the signed event**. Every event carries an Ed25519
signature over canonical bytes; every signature is verified before
dispatch; every event is persisted with the PII redacted. The
result is a system whose event history can be inspected, replayed,
and defended.

## The lifecycle of a signed event

```
   create         sign         publish        handle        persist       audit         replay
     │             │             │             │             │             │             │
     ▼             ▼             ▼             ▼             ▼             ▼             ▼
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
│ Message │──▶│ Ed25519 │──▶│   Bus   │──▶│ Service │──▶│  Store  │──▶│  Audit  │──▶│   DLQ   │
└─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘
                 │                            │                            │
                 ▼                            ▼                            ▼
            identity.pubkey            authz.verify_signature           PII redaction
            AccessControl              AccessControl                    redact_event
            replay_window_sec
```

## Ed25519 signatures

Every event carries an Ed25519 signature over the canonical signing
bytes — `event_id | timestamp | event_type | source | payload`. The
signature is computed at publish time and verified at dispatch.

```python
from underwrite.message import Message
from underwrite.keypair import Keypair

kp = Keypair.create("compliance")
msg = Message.signed(
    kp,
    type="kyc.verified",
    source="compliance",
    payload={"pan": "ABCDE1234F", "result": "verified"},
)
# msg.signature now holds the base64-encoded Ed25519 signature.
```

### Why Ed25519

- **Deterministic.** No random nonce; the same input produces the
  same signature. Verification reproduces it byte-for-byte.
- **Small signatures.** 64 bytes per signature, 32 bytes per
  public key. Negligible bandwidth overhead.
- **Fast.** Ed25519 verification is sub-microsecond on modern CPUs.
- **Standard.** The `cryptography` package implements it; the
  signature is interoperable with anything that supports
  Ed25519.

### Canonical signing bytes

The signature is over a deterministic serialization:

```
event_id | timestamp | event_type | source | <sorted-key JSON payload>
```

`sort_keys=True` is mandatory. `default=str` is forbidden — callers
must serialise non-JSON-native values (datetime, Decimal, UUID)
before publishing, or accept the `ProtocolError` raised at
construction.

## Replay window

A configurable window (default 5 minutes) bounds the lifetime of a
signature. Events older than the window — or dated more than the
window into the future — are rejected at verification.

```yaml
authz:
  enabled: true
  replay_window_seconds: 300
```

Set to 0 (or negative) to disable the window check. The runtime
warns at startup when the window is disabled.

The window defends against:

- **Replay attacks.** An attacker captures an event from a trusted
  publisher and rebroadcasts it; the replay window expires before
  the capture becomes useful.
- **Back-dated forgery.** An attacker who somehow obtains a private
  key cannot back-date events to cover their tracks; old captures
  fall outside the window.

## PII redaction

The audit service persists every event after redacting PAN,
Aadhaar, and other token-matched identifiers. The same redaction
applies to the DLQ and to the Prometheus exporter.

The redaction is **field-aware**: a payload like
`{"pan": "ABCDE1234F"}` becomes
`{"pan": "***REDACTED***"}` — the field name survives, the value
does not.

```python
from underwrite.pii import redact_event

sanitized = redact_event(event)
# sanitized.payload["pan"] == "***REDACTED***"
# sanitized.payload["loan_id"] == "L100"  # non-PII field passes through
```

The redaction rules are configured per environment:

```yaml
pii:
  redact_pan: true
  redact_aadhaar: true
  redact_phone: true
  redact_email: true
  custom_tokens: ["LOAN_ID"]  # additional token-like fields
```

## Deterministic event records

Canonical signing bytes use:

- **Sorted JSON keys.** Two processes producing the same payload
  in different insertion orders produce identical bytes.
- **Strict JSON serialization.** No `default=str` coercion — the
  signer and verifier must agree on the wire format.
- **UUIDv4 event_ids.** Globally unique without coordination.

The result is reproducible signatures across Python versions, across
hosts, across timezones.

## Authorization

`AccessControl` is **default-deny**. An empty ACL denies every
operation. Operators opt into policies through a policy file or
explicit allow rules.

The runtime trusts the runtime identity at startup, before the bus
is constructed, so any event the runtime publishes is verifiable
immediately.

## Bounded surfaces

| Surface | Bounded by | Default |
|---------|------------|---------|
| DLQ records | `max_records` × `max_bytes` | 10,000 records / 16 MiB |
| Idempotency cache | `max_ids_per_handler` × `max_handlers` | 1,000 × 50 |
| Metric entries | `max_metrics` (per type) | 10,000 / 3 |
| Rate-limit buckets | `max_buckets` (LRU) | 10,000 |

Every bounded surface evicts deterministically — oldest first by
timestamp or least-recently-touched by access. The runtime cannot
silently grow without bound.

## What is not in scope

- **Confidential computing.** The runtime signs and verifies
  events; it does not attest the host platform. Use a TEE if you
  need hardware-rooted trust.
- **HSM-backed keys.** Ed25519 private keys live in process memory
  by default. Use Vault or AWS Secrets Manager for durable,
  secret-managed keys. HSM integration is a partner-specific
  extension.
- **Rate limiting at the network layer.** The runtime's
  `Limiter` is per-subscriber and in-process. Network-level
  throttling belongs to your load balancer or service mesh.

## Audit log

Every event is appended to the audit service's ledger after PII
redaction. The ledger is JSONL on disk by default and bounded to a
configurable size (`max_ledger`).

```bash
underwrite health
# {"bus": {...}, "store": {...}, "authz": {...}, "metrics": {...}, "audit": {...}}
```

The audit service exposes a `snapshot()` method that returns the
in-memory view and a `flush()` method that forces a sync to disk.

## Verifying the security posture

```bash
# Run the full test suite — every security control is exercised.
pytest tests/ -v

# Specifically:
pytest tests/test_authz.py tests/test_message.py tests/test_pii.py -v
```

These tests assert the security posture in CI. They fail if a
control regresses.

## See also

- [Architecture](architecture.md) — the layered design that makes the security properties possible.
- [Compliance](compliance.md) — how security controls intersect with RBI / DPDPA requirements.
- [Failure handling](failure-handling.md) — what happens when the security posture is exercised under load.