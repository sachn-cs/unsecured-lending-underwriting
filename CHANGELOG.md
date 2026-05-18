# Changelog

All notable changes to the ULU middleware project are documented in this file.

## 0.2.0 (2026-05-19)

### Added
- Recovery agent assignment and performance tracking
- Legal notice generation per SARFAESI Act (60/90/120-day notices)
- Bankruptcy/IBC proceeding tracking
- DLG pool reconciliation service
- AML screening audit trail
- Secret management abstraction (env, Vault, AWS)
- RBI complaint management with SLA tracking
- Velocity check anti-fraud service
- Insurance tracking for collateral policies
- OpenTelemetry-compatible tracing stub
- Response caching middleware for read-heavy endpoints
- ProtocolSnapshot gzip compression
- Portfolio summary materialized view service
- Redis-backed idempotency cache with in-memory fallback
- Query cache with TTL decorator support
- Blue/green Kubernetes deployment manifests
- Transaction monitoring rules engine
- Prometheus AlertManager rules for error rates, latency, DLG pool

### Improved
- KYC/AML service now persists AML audit records
- `/state` endpoint returns typed `StateResponse` instead of raw dict
- All repository update methods raise `NotFoundError` on missing entities

## 0.1.0 (2026-05-18)

### Added
- Initial FastAPI application with modular routers
- SQLAlchemy 2.0 async ORM with PostgreSQL support
- Alembic migration tooling
- Prometheus metrics and structured JSON logging
- Circuit breakers for external API resilience
- Algorand blockchain client with transaction submission
- Multi-signature wallet support
- NPA aging scheduler and automated triggers
- Dynamic pricing service
- Early warning system with ML-based risk signals
- Device fingerprinting for synthetic identity detection
- API key management with scope and revocation
