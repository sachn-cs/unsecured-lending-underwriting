"""Admin inspection and control endpoints."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request

from ulu import AppendOnlyLedger, DelegatedUnderwriting
from ulu.api.deps import require_admin
from ulu.api.schemas import GraphResponse, SolvencyResponse, StatusResponse, UtilizationResponse
from ulu.api.service import ProtocolService, get_protocol_service, graph_payload, limiter, safe_call
from ulu.infra.logging import logger

router = APIRouter()

_ADMIN_CACHE_TTL = 30.0
_admin_cache: dict[str, tuple[Any, float]] = {}


def clear_admin_cache() -> None:
    """Clears the admin endpoint response cache."""
    _admin_cache.clear()


def _cached(key: str, factory: Callable[[], Any]) -> Any:
    now = time.time()
    if key in _admin_cache:
        value, ts = _admin_cache[key]
        if now - ts < _ADMIN_CACHE_TTL:
            return value
    value = factory()
    _admin_cache[key] = (value, now)
    return value


@router.get("/admin/graph", response_model=GraphResponse)
async def admin_graph(
    _: None = Depends(require_admin),
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> GraphResponse:
    with protocol_service.lock:
        payload = _cached("graph", lambda: graph_payload(protocol_service))
    return GraphResponse(
        seeds=payload["seeds"],
        parent=payload["parent"],
        edges=payload["edges"],
    )


@router.get("/admin/utilization", response_model=UtilizationResponse)
async def admin_utilization(
    _: None = Depends(require_admin),
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> UtilizationResponse:
    with protocol_service.lock:
        util = _cached(
            "utilization",
            lambda: safe_call(protocol_service.engine.seed_delegation_utilization),
        )
    return UtilizationResponse(delegation_utilization=util)


@router.get("/admin/solvency", response_model=SolvencyResponse)
async def admin_solvency(
    _: None = Depends(require_admin),
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> SolvencyResponse:
    with protocol_service.lock:
        safe_call(protocol_service.engine.assert_invariants)
        required: dict[str, float] = {}
        for user in sorted(protocol_service.engine.earned):
            if user not in protocol_service.engine.seeds:
                required[user] = protocol_service.engine.required_delegation(user)
    return SolvencyResponse(invariants="ok", required_delegation=required)


@router.post("/admin/reset", response_model=StatusResponse)
@limiter.limit("5/minute")
async def admin_reset(
    request: Request,
    _: None = Depends(require_admin),
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> StatusResponse:
    with protocol_service.lock:
        protocol_service.ledger = AppendOnlyLedger()
        protocol_service.engine = DelegatedUnderwriting(ledger=protocol_service.ledger)
        protocol_service.idempotency_cache.clear()
    _admin_cache.clear()
    logger.info("admin_reset_executed")
    return StatusResponse(status="ok")
