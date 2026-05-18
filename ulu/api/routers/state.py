"""State persistence endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ulu import DelegatedUnderwriting
from ulu.api.schemas import LoadRequest, SaveRequest, StateResponse, StatusResponse
from ulu.api.service import ProtocolService, _validate_path, get_protocol_service, limiter, safe_call

router = APIRouter()


@router.get("/state", response_model=StateResponse)
async def get_state(protocol_service: ProtocolService = Depends(get_protocol_service)) -> StateResponse:
    with protocol_service.lock:
        return StateResponse(state=protocol_service.engine.to_dict())


@router.post("/state/save", response_model=StatusResponse)
@limiter.limit("20/minute")
async def save_state(
    request: Request,
    body: SaveRequest,
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> StatusResponse:
    target = _validate_path(body.path)
    with protocol_service.lock:
        safe_call(lambda: protocol_service.engine.save_json(str(target)))
    return StatusResponse(status="ok")


@router.post("/state/load", response_model=StatusResponse)
@limiter.limit("20/minute")
async def load_state(
    request: Request,
    body: LoadRequest,
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> StatusResponse:
    target = _validate_path(body.path)

    def load_action() -> None:
        protocol_service.engine = DelegatedUnderwriting.load_json(str(target))
        protocol_service.engine.ledger = protocol_service.ledger

    with protocol_service.lock:
        safe_call(load_action)
    return StatusResponse(status="ok")
