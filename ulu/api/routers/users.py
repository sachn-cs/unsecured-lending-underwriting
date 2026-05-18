"""User delegation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from ulu.api.schemas import StatusResponse, UserRequest
from ulu.api.service import ProtocolService, get_protocol_service, idempotent_mutation, limiter, safe_call

router = APIRouter()


@router.post("/user", response_model=StatusResponse)
@limiter.limit("10/minute")
async def add_user(
    request: Request,
    body: UserRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> StatusResponse:
    def action() -> StatusResponse:
        safe_call(
            lambda: protocol_service.engine.add_user(
                body.sponsor,
                body.user,
                body.delegation_amount,
            )
        )
        return StatusResponse(status="ok")

    with protocol_service.lock:
        return idempotent_mutation(
            "add_user", body.model_dump(), action, idempotency_key, protocol_service
        )
