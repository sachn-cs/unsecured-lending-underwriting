# Troubleshooting

Common issues encountered when running the underwrite platform, their root causes, diagnostic steps, and resolutions.

---

## 1. "cryptography library not available" warning

**Symptom**: Warning logged at startup: "cryptography library not available — event signatures will not be verified". Ed25519 signature verification in `AccessControl.verify_signature()` silently returns `True` for all signatures.

**Root cause**: The `cryptography` package is not installed. Signature verification is bypassed — insecure, development-only mode.

**Diagnostic steps**:
```
pip list | grep cryptography
python -c "import cryptography; print(cryptography.__version__)"
```

**Resolution**:
```
pip install "cryptography>=41.0"
```
For production deployments, this is a core dependency and is always installed. This warning only appears if the package is missing from the environment (e.g. partial install, broken venv).

---

## 2. Event signature verification failures

**Symptom**: `AuthzError: invalid signature on event {id} from {source}` logged in the dispatching service. Events are silently dropped.

**Root cause**: The emitting service signed the event with a private key whose corresponding public key does not match the `source_key` in the event envelope. This happens when:
- A service was restarted and regenerated its Ed25519 keypair (`Identity.create()` generates a fresh key each call).
- The `source_key` in the event metadata was tampered with or misconfigured.
- Key rotation occurred mid-flight and the verifier does not have the old key in its trust set. Configure a longer `AccessControl.set_replay_window(...)` so recent signatures keep verifying during rotation.

**Diagnostic steps**:
1. Check the event's `source` and `source_key` fields:
   ```
   underwrite dlq  # shows failed events
   ```
2. Verify the expected public key for the source service matches what is in `AccessControl.__trusted_keys`.
3. Check identity configuration: `identity.private_key` and `identity.public_key` in `underwrite.json`.
4. Look for `identity.registered` or `identity.rotated` events in the audit ledger.

**Resolution**:
- If keys were regenerated, re-register the new public key via the identity service or update `AccessControl.__trusted_keys`.
- For in-flight signatures during a key rotation, set
  `AccessControl.set_replay_window(...)` long enough to cover the
  expected signature lifetime.
- For testing, pass the same `private_key_pem` to `Identity.create()` on every start, or persist the key material to a secrets backend.

---

## 3. Rate limit exceeded

**Symptom**: `RateLimitError: rate limit exceeded for sub:{id}` logged. Events are sent to the dead-letter queue with error `"rate_limited"`.

**Root cause**: The `RateLimiter` token-bucket (per subscriber) has exceeded its configured `max_rate` within the `interval` window. The default rate limit is `0.0` (unlimited) — this only triggers when `bus.rate_limit` > 0 in configuration or `UNDERWRITE_BUS_RATE_LIMIT` is set.

**Diagnostic steps**:
1. Check the current rate limit config:
   ```
   underwrite config  # or inspect underwrite.json
   ```
2. Look for `UNDERWRITE_BUS_RATE_LIMIT` environment variable.
3. Monitor `bus.rate_limit` in the health endpoint.
4. Check how many events per second the subscriber receives.

**Resolution**:
- Increase `UNDERWRITE_BUS_RATE_LIMIT` or `bus.rate_limit` in config.
- Reduce event publishing frequency.
- If using `DistributedRateLimiter`, ensure the shared store is reachable and not a bottleneck.
- Set `bus.rate_limit` to `0.0` (or omit) to disable rate limiting entirely.

---

## 4. Circuit breaker open

**Symptom**: `CircuitBreakerOpenError: circuit {name} is open` logged. Operations against a store or subscriber are rejected immediately without attempting the call. Failed events go to DLQ with error `"circuit_open"`.

**Root cause**: The `CircuitBreaker` (in `underwrite/circuit.py`) has recorded `failure_threshold` consecutive failures (default 5 for bus subscribers, 3 for `PostgresStore`/`FileStore`). The circuit transitions from CLOSED → OPEN, rejecting all requests until `recovery_timeout` elapses (default 60s for bus, 15s for Postgres, 30s for FileStore).

**Diagnostic steps**:
1. Check circuit state via health endpoint:
   ```
   underwrite health  # shows circuit states for stores
   ```
2. Identify which subscriber or store is failing (check DLQ):
   ```
   underwrite dlq
   ```
3. Check the underlying store or handler logs for the root error.
4. For `PostgresStore`, check `SELECT 1` connectivity and `pg_stat_activity` for stuck queries.

**Resolution**:
- Wait for `recovery_timeout` seconds (default 15s for Postgres, 30s for FileStore). The circuit transitions to HALF_OPEN → CLOSED on the next successful probe.
- Fix the underlying store issue (Postgres down, disk full, etc.).
- If the circuit is persistently opening, increase `failure_threshold` or `recovery_timeout` in the constructor.
- To reset immediately: restart the runtime.

---

## 5. Migration failed

**Symptom**: `MigrationError: migration v{N} ({description}) failed: {details}` logged at startup. The runtime may continue with partial schema state.

**Root cause**: A SQL migration statement failed (e.g. table already exists with different schema, constraint violation, permission denied). The migration runs inside a transaction — a failure rolls back that migration but previously applied migrations remain committed.

**Diagnostic steps**:
1. Check the applied migrations table:
   ```sql
   SELECT * FROM migrations ORDER BY version;
   ```
2. Check the failing migration SQL in `underwrite/migrate.py` (the `default_plan()` function).
3. Check Postgres logs for the exact SQL error.

**Resolution**:
- Roll back the failed migration version:
  ```sql
  DELETE FROM migrations WHERE version = N;
  ```
- Fix the schema issue manually, or fix the migration SQL in `default_plan()` and re-run.
- To skip the failed migration entirely, insert a record manually:
  ```sql
  INSERT INTO migrations (version, description) VALUES (N, 'manual skip');
  ```
- If `migration.auto_migrate` is `true`, set it to `false` to prevent auto-migration on startup, then run `underwrite migrate` after fixes.

---

## 6. Saga not executing

**Symptom**: A saga remains in `"started"` status indefinitely. No forward events are emitted. `SAGA_COMPLETED` / `SAGA_ROLLED_BACK` never fire.

**Root cause**: One of:
- The saga orchestrator is disabled (`config.saga.enabled = false`).
- The emitter for the saga name was never registered (no `register_emitter()` call).
- The saga steps list is empty or contains invalid step indices.
- The `execute_all()` or `execute_step()` methods are never invoked.

**Diagnostic steps**:
1. Check saga config: `config.saga.enabled`.
2. Check registered emitters: `SagaOrchestrator.__emitters` keys.
3. Inspect persisted saga state:
   ```
   # from the store:
   store.get("saga:{saga_id}")
   ```
4. Verify service wiring — the emitter service must be started and subscribed to its own events (see `Runtime.wire()` in `runtime.py`).

**Resolution**:
- Enable sagas: `UNDERWRITE_SAGA_ENABLED=true`.
- Ensure the emitter service calls `saga.register_emitter(saga_name, self)` (done automatically in `NanoService.__init__` when a `SagaOrchestrator` is passed).
- Call `orchestrator.start_saga(name, steps)` followed by `orchestrator.execute_all(saga_id)`.
- For crashed sagas, use `orchestrator.replay_saga(saga_id)` or `Runtime.replay_saga(saga_id)`.

---

## 7. Dead letter queue filling up

**Symptom**: `underwrite dlq` shows many entries. Events are failing processing.

**Root cause**: Handlers are raising unhandled exceptions. Each failure sends the event to the DLQ (`DeadLetterQueue.put()`) and increments the circuit breaker failure count.

**Diagnostic steps**:
```
# List recent DLQ entries
underwrite dlq

# Check which subscriber and error
underwrite dlq --max 50
```
Inspect the `error` field — it contains the exception type and message.

**Resolution**:
1. Fix the underlying handler error (check logs for the full traceback).
2. Replay dead-letter events after the fix:
   ```
   underwrite dlq --replay
   ```
3. For bulk failures, clear the DLQ:
   ```
   underwrite dlq --clear  # or call DeadLetterQueue.clear()
   ```
4. If the DLQ is filling due to circuit breaker or rate limiting, address the root cause first.

---

## 8. Service not receiving events

**Symptom**: A service's `handle()` method is never called for events it should process. Service stays idle.

**Root cause**: The service is not wired to the event types it should receive. Either:
- The service is not registered in `WIRING` in `underwrite/handler.py`.
- The service name is missing from the `WIRING` entry for the relevant `EventType`.
- The service was not started with `runtime.start([...])`.
- The service's `subscribe()` method found no matching entries in `WIRING`.

**Diagnostic steps**:
1. Check `WIRING` in `underwrite/handler.py` for the event type and service name.
2. Verify the service is started:
   ```
   underwrite health  # check "services" section
   ```
3. Check that `Runtime.wire(service_name)` was called (it is called in `Runtime.start()`).
4. Verify the service's `__init__` does not override subscriptions.

**Resolution**:
- Add the service to the appropriate `WIRING` entry.
- Ensure the service is listed in the `Runtime.start()` call or in `config.services` with `enabled: true`.
- If a service needs to listen for all events (like `audit`), ensure `"*"` is in its wiring or it subscribes to `"*"` explicitly via `svc.subscribe("*")`.

---

## 9. Postgres connection failures

**Symptom**: `StoreError: Postgres health check failed`, `OperationalError: could not connect to server`, or circuit breaker trips on `PostgresStore`.

**Root cause**: The Postgres server is unreachable, credentials are wrong, or the connection pool is exhausted.

**Diagnostic steps**:
1. Check `UNDERWRITE_STORE_DSN` for correct host, port, database, user, and password.
2. Test connectivity:
   ```
   psql "$UNDERWRITE_STORE_DSN" -c "SELECT 1"
   ```
3. Check `UNDERWRITE_STORE_POOL_SIZE` (default 5) — too low for concurrent handler threads.
4. Check `statement_timeout` — PostgresStore sets it to `operation_timeout * 1000` ms (default 30s).
5. Inspect `pg_stat_activity` for stuck queries or idle-in-transaction connections.
6. Check `pg_stat_database` for deadlocks or lock contention.

**Resolution**:
- Verify DSN format: `postgresql://user:pass@host:port/dbname`.
- Increase `pool_size` to match the number of concurrent workers.
- Check network connectivity and firewall rules.
- Ensure `statement_timeout` is appropriate for your workload.
- The `PostgresStore` uses `ThreadedConnectionPool` with `keepalives=1`, `keepalives_idle=30`, `keepalives_interval=10`, `keepalives_count=5` for connection health.
- If the circuit breaker is open, wait `recovery_timeout` (15s) automatically.

---

## 10. Duplicate events

**Symptom**: A handler processes the same event twice. State updates are applied multiple times.

**Root cause**: The `IdempotencyGuard` is not working, or the event was published with a duplicate `event_id`. The guard tracks `(handler_id, event_id)` pairs, but if the guard's `max_ids_per_handler` limit is reached, oldest entries are evicted and duplicates may be accepted.

**Diagnostic steps**:
1. Check that `IdempotencyGuard.is_duplicate()` is being called (it is called in `NanoService.__dispatch()` at `underwrite/services/base.py:307`).
2. Check `bus.idempotency.total_tracked_events` to see if the guard is populated.
3. Check event IDs for collisions — `event_id` is a UUID4 by default, but if manually set, verify uniqueness.
4. Check `max_ids_per_handler` (default 100000) — if the service handles many unique events, old entries are evicted and duplicates may slip through.

**Resolution**:
- Increase `max_ids_per_handler` if the service handles more than 100000 unique events.
- Ensure event publishers generate unique `event_id` values (UUID4).
- The `DUPLICATE_DROPPED` event type (`idempotency.duplicate_dropped`) can be monitored for duplicate detection activity.
- Consider using a persistent idempotency store (the current implementation is in-memory only).

---

## 11. Memory growth

**Symptom**: RSS grows over time. Eventually OOM-killed or swap thrashing.

**Root cause**: One or more in-memory data structures grow unbounded:
- `FraudService.__records` — `OrderedDict[str, deque]` bounded by `MAX_BORROWERS=100000` and `maxlen=1000` per borrower (default max ~100M entries worst case).
- `AuditService.__ledger` — `deque` capped at `max_ledger` (default 100000).
- `MetricsCollector` — bounded at `max_metrics=10000`.
- `Tracer.__spans` — bounded at `max_spans=10000`.
- `DeadLetterQueue.__records` — bounded at `max_records=10000`.
- `IdempotencyGuard.__seen` — bounded at `max_ids_per_handler=100000`.

**Diagnostic steps**:
1. Check `AuditService.__max_ledger` — this is the largest default buffer.
2. Check `FraudService.MAX_BORROWERS` — if many borrowers, records grow.
3. Check `UNDERWRITE_AUDIT_MAX_LEDGER` env var.
4. Use `underwrite metrics` to check counters and identify which service has high activity.

**Resolution**:
- Reduce `max_ledger` in audit config: `UNDERWRITE_AUDIT_MAX_LEDGER=10000`.
- For `FraudService`, reduce `MAX_BORROWERS` or `maxlen` per borrower.
- Enable audit export to S3/GCS to offload the in-memory ledger.
- If using `Tracer` with `ConsoleSpanExporter`, spans are kept in memory — set `max_spans` lower.
- Set `config.metrics.enabled = false` if metrics are not needed.

---

## 12. Configuration not applied

**Symptom**: Changes to `underwrite.json` or environment variables have no effect.

**Root cause**: The configuration file is not being loaded (wrong path, JSON parse error, unknown keys rejected), or environment variables are not matching the expected names.

**Diagnostic steps**:
1. Check which config file is loaded:
   - The loader searches for explicitly provided path, then `config.{UNDERWRITE_ENV}.json`.
   - If neither exists, `Configuration.default()` is used.
2. Enable debug logging: `UNDERWRITE_LOG_LEVEL=DEBUG`.
3. Check for JSON parse errors in the log.
4. Verify environment variable names:
   ```
   env | grep UNDERWRITE_
   ```
5. Check for unknown keys — `Configuration.__merge()` rejects keys not in `known_keys`.

**Resolution**:
- Ensure the correct config file path is provided or `underwrite.json` exists in the working directory.
- For env vars, set `UNDERWRITE_ENV=production` and place config in `config.production.json`.
- Check the exact env var names in `config.py:__apply_env_overrides()`.
- Boolean env vars accept `"1"`, `"true"`, `"yes"` (case-insensitive).
- Numeric env vars that fail coercion are logged and skipped (not fatal).

---

## 13. Docker container crash

**Symptom**: Container exits with non-zero code. `docker logs` shows `HEALTHCHECK` failure or Python traceback.

**Root cause**: The `HEALTHCHECK` in `Dockerfile` calls `underwrite health` which aggregates all subsystem health checks. If any check fails (bus, store, service), the health command exits with code 1, causing Docker to restart or kill the container.

**Diagnostic steps**:
1. Check container logs:
   ```
   docker logs <container> 2>&1 | tail -50
   ```
2. Check the health check status directly:
   ```
   docker exec <container> underwrite health
   ```
3. Check which specific health check is failing.

**Resolution**:
- Fix the failing subsystem (see relevant troubleshooting section above).
- For transient failures, increase `HEALTHCHECK` `--retries` and `--interval` in the Dockerfile.
- If the health check is too strict, adjust the health check functions in `HealthRegistry`.
- Ensure `recovery.auto_restart` is configured to allow the runtime to restart failing services without exiting.

---

## 14. HTTP 401 on publish

**Symptom**: POST `/v1/publish` returns `{"error": "unauthorized", "status_code": 401}`.

**Root cause**: The `Authorization` header is missing, does not start with `Bearer `, or the token does not match `UNDERWRITE_API_TOKEN`. The `serve.py` auth middleware uses `hmac.compare_digest()` for constant-time comparison.

**Diagnostic steps**:
1. Check the request headers:
   ```
   curl -v -X POST http://localhost:8080/v1/publish -H "Authorization: Bearer <token>"
   ```
2. Verify `UNDERWRITE_API_TOKEN` is set:
   ```
   echo "$UNDERWRITE_API_TOKEN"
   ```
3. Check if `require_auth` is enabled (by default it is not — only when `--require-auth` is passed).

**Resolution**:
- Ensure every request includes `Authorization: Bearer <token>`.
- Ensure `UNDERWRITE_API_TOKEN` env var matches the token in the request.
- If authentication is not needed, start the server without `--require-auth`.
- If the server was started with `--require-auth` but `UNDERWRITE_API_TOKEN` is unset, it raises `ValueError` at startup.
