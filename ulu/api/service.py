"""Thread-safe runtime service and helpers used by API handlers."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ulu import AppendOnlyLedger, DelegatedUnderwriting
from ulu.errors import ProtocolError
from ulu.infra.config import settings
from ulu.infra.logging import logger

_IDEMPOTENCY_MAX_SIZE = 10_000
_DATA_DIR = Path(os.environ.get("ULU_DATA_DIR", "/tmp/ulu_data"))


class ProtocolService:
    """Holds thread-safe runtime objects used by API handlers."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.ledger = AppendOnlyLedger()
        self.engine = DelegatedUnderwriting(ledger=self.ledger)
        self.idempotency_cache: dict[str, tuple[str, dict[str, Any]]] = {}

    def _prune_idempotency_cache(self) -> None:
        if len(self.idempotency_cache) > _IDEMPOTENCY_MAX_SIZE:
            keys = list(self.idempotency_cache.keys())
            for key in keys[: len(keys) // 4]:
                self.idempotency_cache.pop(key, None)


def _ensure_data_dir() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _validate_path(raw: str) -> Path:
    _ensure_data_dir()
    target = (_DATA_DIR / raw).resolve()
    try:
        target.relative_to(_DATA_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid path: must be inside data directory") from exc
    return target


def safe_call(fn: Callable[[], Any]) -> Any:
    """Maps protocol errors to HTTP 400 responses; logs unexpected errors."""
    try:
        return fn()
    except ProtocolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("unexpected_error", context="safe_call")
        raise HTTPException(status_code=500, detail="internal server error") from exc


def ledger_events_payload(protocol_service: ProtocolService) -> list[dict[str, Any]]:
    """Returns serialized ledger event payloads."""
    return [
        {
            "seq": event.seq,
            "event_type": event.event_type,
            "payload": event.payload,
            "timestamp_utc": event.timestamp_utc,
        }
        for event in protocol_service.ledger.events()
    ]


def canonical_request_hash(payload: Mapping[str, Any]) -> str:
    """Creates deterministic hash for idempotent mutation payload."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(blob.encode("utf-8")).hexdigest()


def idempotent_mutation(
    operation_name: str,
    payload: Mapping[str, Any],
    action: Callable[[], Any],
    idempotency_key: str | None,
    protocol_service: ProtocolService,
) -> Any:
    """Executes idempotent mutation when idempotency key is provided."""
    if not idempotency_key:
        return action()

    cache_key = f"{operation_name}:{idempotency_key}"
    payload_hash = canonical_request_hash(payload)
    cached = protocol_service.idempotency_cache.get(cache_key)
    if cached is not None:
        cached_hash, cached_response = cached
        if cached_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail="idempotency key replayed with different payload",
            )
        return cached_response

    response = action()
    protocol_service._prune_idempotency_cache()
    protocol_service.idempotency_cache[cache_key] = (payload_hash, response)
    return response


def quote_response_payload(quote: Any) -> dict[str, Any]:
    """Builds response payload for quote-like operations."""
    return {
        "borrower": quote.borrower,
        "principal": quote.principal,
        "term": quote.term,
        "protocol_premium": quote.protocol_premium,
        "delegation_premium": quote.delegation_premium,
        "total_interest": quote.total_interest,
        "delegation_utilization": quote.delegation_utilization,
        "delegation_rate": quote.delegation_rate,
        "locked_by_edge": {f"{source}->{target}": amount for (source, target), amount in quote.locked_by_edge.items()},
        "delegation_payouts": quote.delegation_payouts,
    }


def graph_payload(protocol_service: ProtocolService) -> dict[str, Any]:
    """Builds graph view for admin inspection."""
    edges = [
        {"sponsor": sponsor, "child": child, "amount": amount}
        for (sponsor, child), amount in sorted(protocol_service.engine.delegation.items())
    ]
    return {
        "seeds": sorted(protocol_service.engine.seeds),
        "parent": dict(protocol_service.engine.parent),
        "edges": edges,
    }


async def _db_is_healthy() -> bool:
    """Checks PostgreSQL connectivity when DATABASE_URL is configured."""
    if not settings.database_url:
        return True
    try:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


service = ProtocolService()
limiter = Limiter(key_func=get_remote_address)


def get_protocol_service() -> ProtocolService:
    return service


def get_limiter() -> Limiter:
    return limiter
