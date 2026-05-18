"""Bulk operations API for batch seed creation and user onboarding.

Item 65 from production roadmap.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ulu.api.schemas import SeedRequest
from ulu.api.service import ProtocolService, get_protocol_service
from ulu.errors import InfeasibleOperationError, ProtocolError

router = APIRouter()


@router.post("/bulk/seeds")
async def bulk_create_seeds(
    requests: list[SeedRequest],
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> dict[str, list[dict[str, str]]]:
    """Creates multiple seeds in a single request.

    Stops on first failure and returns partial results.
    """
    created: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    with protocol_service.lock:
        for req in requests:
            try:
                protocol_service.engine.add_seed(req.user, req.base_budget)
                created.append({"user": req.user, "status": "created"})
            except ProtocolError as exc:
                errors.append({"user": req.user, "error": str(exc)})
    return {"created": created, "errors": errors}


@router.post("/bulk/users")
async def bulk_create_users(
    payloads: list[dict],
    protocol_service: ProtocolService = Depends(get_protocol_service),
) -> dict[str, list[dict[str, str]]]:
    """Onboards multiple users with delegation in a single request.

    Each payload must contain: sponsor, user, delegation_amount.
    """
    created: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    with protocol_service.lock:
        for payload in payloads:
            try:
                sponsor = payload.get("sponsor")
                user = payload.get("user")
                amount = payload.get("delegation_amount")
                if not all(isinstance(v, (str, int, float)) for v in (sponsor, user, amount)):
                    errors.append({"user": str(user), "error": "invalid payload"})
                    continue
                protocol_service.engine.add_user(sponsor, user, float(amount))
                created.append({"user": str(user), "status": "created"})
            except (ProtocolError, InfeasibleOperationError) as exc:
                errors.append({"user": str(payload.get("user")), "error": str(exc)})
    return {"created": created, "errors": errors}
