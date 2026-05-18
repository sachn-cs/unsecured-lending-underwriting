"""Health, readiness, and metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from ulu.api.schemas import HealthResponse, LiveResponse, ReadyResponse
from ulu.api.service import ProtocolService, _db_is_healthy, get_protocol_service
from ulu.errors import ProtocolError

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="alive")


@router.get("/ready", response_model=ReadyResponse)
async def ready(protocol_service: ProtocolService = Depends(get_protocol_service)) -> ReadyResponse:
    with protocol_service.lock:
        try:
            protocol_service.engine.assert_invariants()
        except ProtocolError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not await _db_is_healthy():
        raise HTTPException(status_code=503, detail="database unreachable")
    return ReadyResponse(status="ready")


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
