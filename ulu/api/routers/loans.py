"""Loan quote, origination, and default endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from ulu.api.schemas import DefaultRequest, OriginateResponse, QuoteRequest, QuoteResponse, StatusResponse
from ulu.api.service import (
    ProtocolService,
    get_protocol_service,
    idempotent_mutation,
    limiter,
    quote_response_payload,
    safe_call,
)

router = APIRouter()


@router.post("/quote", response_model=QuoteResponse)
@limiter.limit("30/minute")
async def quote(
    request: Request,
    body: QuoteRequest,
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> QuoteResponse:
    with protocol_service.lock:
        quote_value = safe_call(
            lambda: protocol_service.engine.quote_loan(
                borrower=body.borrower,
                principal=body.principal,
                term=body.term,
                default_probability=body.default_probability,
                protocol_rate=body.protocol_rate,
                max_delegation_rate=body.max_delegation_rate,
            )
        )
    return QuoteResponse(**quote_response_payload(quote_value))


@router.post("/originate", response_model=OriginateResponse)
@limiter.limit("10/minute")
async def originate(
    request: Request,
    body: QuoteRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> OriginateResponse:
    def action() -> OriginateResponse:
        quote_value = safe_call(
            lambda: protocol_service.engine.originate_loan(
                borrower=body.borrower,
                principal=body.principal,
                term=body.term,
                default_probability=body.default_probability,
                protocol_rate=body.protocol_rate,
                max_delegation_rate=body.max_delegation_rate,
            )
        )
        return OriginateResponse(
            borrower=quote_value.borrower,
            principal=quote_value.principal,
            term=quote_value.term,
            total_interest=quote_value.total_interest,
        )

    with protocol_service.lock:
        return idempotent_mutation(
            "originate", body.model_dump(), action, idempotency_key, protocol_service
        )


@router.post("/default", response_model=StatusResponse)
@limiter.limit("10/minute")
async def default(
    request: Request,
    body: DefaultRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> StatusResponse:
    def action() -> StatusResponse:
        safe_call(lambda: protocol_service.engine.default(body.borrower))
        return StatusResponse(status="ok")

    with protocol_service.lock:
        return idempotent_mutation(
            "default", body.model_dump(), action, idempotency_key, protocol_service
        )
