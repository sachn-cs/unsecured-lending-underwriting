"""Pydantic request and response models for the ULU API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from ulu.api.validators import validate_aadhaar, validate_pan


class SeedRequest(BaseModel):
    user: str
    base_budget: float = Field(gt=0)


class UserRequest(BaseModel):
    sponsor: str
    user: str
    delegation_amount: float = Field(gt=0)


class RepayRequest(BaseModel):
    user: str
    delta_earned: float = Field(ge=0)


class RevokeRequest(BaseModel):
    sponsor: str
    child: str
    new_delegation: float = Field(ge=0)


class QuoteRequest(BaseModel):
    borrower: str
    principal: float = Field(gt=0)
    term: float = Field(gt=0)
    default_probability: float = Field(gt=0, lt=1)
    protocol_rate: float = Field(ge=0, le=10.0)
    max_delegation_rate: float = Field(ge=0, le=10.0)


class DefaultRequest(BaseModel):
    borrower: str


class SaveRequest(BaseModel):
    path: str


class LoadRequest(BaseModel):
    path: str


class LedgerSaveRequest(BaseModel):
    path: str


class LedgerLoadRequest(BaseModel):
    path: str


class StatusResponse(BaseModel):
    status: str


class QuoteResponse(BaseModel):
    borrower: str
    principal: float
    term: float
    protocol_premium: float
    delegation_premium: float
    total_interest: float
    delegation_utilization: float
    delegation_rate: float
    locked_by_edge: dict[str, float]
    delegation_payouts: dict[str, float]


class OriginateResponse(BaseModel):
    borrower: str
    principal: float
    term: float
    total_interest: float


class StateResponse(BaseModel):
    state: dict[str, Any]


class LedgerResponse(BaseModel):
    events: list[dict[str, Any]]


class GraphResponse(BaseModel):
    seeds: list[str]
    parent: dict[str, str]
    edges: list[dict[str, Any]]


class UtilizationResponse(BaseModel):
    delegation_utilization: float


class SolvencyResponse(BaseModel):
    invariants: str
    required_delegation: dict[str, float]


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str


class LiveResponse(BaseModel):
    status: str


class KycRequest(BaseModel):
    borrower_id: str
    pan_number: str = ""
    aadhaar_hash: str = ""

    @field_validator("pan_number")
    @classmethod
    def _check_pan(cls, v: str) -> str:
        if v and not validate_pan(v):
            raise ValueError("invalid PAN format")
        return v

    @field_validator("aadhaar_hash")
    @classmethod
    def _check_aadhaar(cls, v: str) -> str:
        if v and not validate_aadhaar(v):
            raise ValueError("invalid Aadhaar format")
        return v


class ErrorResponse(BaseModel):
    detail: str
