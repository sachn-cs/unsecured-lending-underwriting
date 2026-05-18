"""Delegation revocation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from ulu.api.schemas import RevokeRequest, StatusResponse
from ulu.api.service import ProtocolService, get_protocol_service, idempotent_mutation, limiter, safe_call

router = APIRouter()


@router.post("/revoke", response_model=StatusResponse)
@limiter.limit("10/minute")
async def revoke(
    request: Request,
    body: RevokeRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> StatusResponse:
    def action() -> StatusResponse:
        safe_call(
            lambda: protocol_service.engine.revoke(
                body.sponsor,
                body.child,
                body.new_delegation,
            )
        )
        return StatusResponse(status="ok")

    with protocol_service.lock:
        return idempotent_mutation(
            "revoke", body.model_dump(), action, idempotency_key, protocol_service
        )
