# DLQ and replay

The dead-letter queue is the runtime's durable record of every
event a subscriber failed to handle. Operations on it — inspect,
clear, replay — are first-class CLI commands.

## Inspecting

```bash
underwrite dlq
```

Shows the most recent 20 records with timestamp, subscriber id,
event type, and error:

```
Dead-letter queue: 3 entries
  [1700000000.1] mechanism: kyc.failed — ValueError: PAN format invalid
  [1700000001.4] pricing: pricing.compute — RuntimeError: rate cap exceeded
  [1700000002.7] audit: audit.append — ConnectionError: store locked
```

The full record count is on the first line.

## Replaying

```bash
underwrite dlq --replay
```

Re-publishes every record in the DLQ back onto the bus. The
idempotency guard ensures that re-delivery does not double-process
the event. The replay:

1. Drains the DLQ (removes all records).
2. Re-publishes each event onto the bus.
3. On per-event failure, puts the event back on the DLQ with a
   `replay_failed` error.

The CLI also supports a cap:

```bash
underwrite dlq --replay --max 100
```

Replays at most 100 records, leaving the rest in the queue.

## Clearing

```bash
underwrite dlq --clear
```

Drops every record. Use this when you have decided the events are
not worth processing (e.g., a batch of poison messages from a
known-broken publisher).

## When to replay

Replay when the **underlying failure has been fixed** and the
events are still relevant:

- A downstream service was down for ten minutes. Fix the service,
  replay the DLQ, the events flow through cleanly.
- A new version of a service rejects an event format that older
  versions accepted. Deploy the new version, replay the DLQ.
- A poison message flooded the DLQ. Identify the publisher,
  disable it, then replay non-poison messages.

## When not to replay

- **Don't replay without diagnosing first.** The DLQ is durable;
  let the records sit while you investigate.
- **Don't replay into a still-broken service.** The events will
  re-enter the DLQ with the same error.
- **Don't replay if the records are stale.** Events from a month
  ago may no longer be relevant to current state; replaying them
  can produce confusing side effects.

## Programmatic access

```python
runtime.bus.dlq.count()        # number of records
runtime.bus.dlq.clear()        # drop everything
runtime.bus.dlq.replay(bus)    # re-publish onto the bus
```

The `Queue` class exposes a stable iteration surface:

```python
for record in runtime.bus.dlq.records.values():
    print(record.timestamp, record.subscriber_id, record.error)
```

## Bounded by default

The DLQ is bounded:

- **`max_records`** (default 10,000): when full, oldest entries are
  evicted.
- **`max_bytes`** (default 16 MiB): when the serialized blob
  exceeds this size, oldest entries are trimmed first.

The persistent store is also dedup-aware: a poison message that
fails repeatedly updates its existing record instead of growing
the DLQ.

## Alerting

Wire your alerting on `runtime.bus.dlq.count()`:

| Threshold | Severity |
|-----------|----------|
| > 0       | Info — investigate |
| > 100     | Warning — first responder paged |
| > 1000    | Critical — significant event loss |

The DLQ should be empty in steady state. Any sustained DLQ growth
is a sign that something is wrong upstream.

## See also

- [Failure handling](../understand/failure-handling.md) — how the DLQ fits with idempotency, circuit breaking, and supervision.
- [Observability](observability.md) — DLQ metrics on `/metrics`.
- [Operations](operations.md) — incident response playbook.