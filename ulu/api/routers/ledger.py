"""Ledger persistence and retrieval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ulu.api.schemas import LedgerLoadRequest, LedgerResponse, LedgerSaveRequest, StatusResponse
from ulu.api.service import ProtocolService, _validate_path, get_protocol_service, ledger_events_payload, limiter
from ulu.audit import AppendOnlyLedger

router = APIRouter()


@router.get("/ledger", response_model=LedgerResponse)
async def get_ledger(protocol_service: ProtocolService = Depends(get_protocol_service)) -> LedgerResponse:
    with protocol_service.lock:
        return LedgerResponse(events=ledger_events_payload(protocol_service))


@router.post("/ledger/save", response_model=StatusResponse)
@limiter.limit("20/minute")
async def save_ledger(
    request: Request,
    body: LedgerSaveRequest,
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> StatusResponse:
    target = _validate_path(body.path)
    with protocol_service.lock:
        protocol_service.ledger.save_jsonl(str(target))
    return StatusResponse(status="ok")


@router.post("/ledger/load", response_model=StatusResponse)
@limiter.limit("20/minute")
async def load_ledger(
    request: Request,
    body: LedgerLoadRequest,
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> StatusResponse:
    target = _validate_path(body.path)
    with protocol_service.lock:
        protocol_service.ledger = AppendOnlyLedger.load_jsonl(str(target))
        protocol_service.engine.ledger = protocol_service.ledger
    return StatusResponse(status="ok")
