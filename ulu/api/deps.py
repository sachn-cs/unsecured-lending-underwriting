"""FastAPI dependency injection providers."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ulu.infra.db import get_db_session
from ulu.infra.repositories import (
    AuditEventRepository,
    CollateralEscrowRepository,
    DefaultRepository,
    IdempotencyRepository,
    LoanRepository,
    NpaEventRepository,
    RepaymentRepository,
    UserRepository,
)


async def get_user_repo(session: AsyncSession = Depends(get_db_session)) -> UserRepository:
    return UserRepository(session)


async def get_loan_repo(session: AsyncSession = Depends(get_db_session)) -> LoanRepository:
    return LoanRepository(session)


async def get_repayment_repo(
    session: AsyncSession = Depends(get_db_session),
) -> RepaymentRepository:
    return RepaymentRepository(session)


async def get_default_repo(
    session: AsyncSession = Depends(get_db_session),
) -> DefaultRepository:
    return DefaultRepository(session)


async def get_collateral_repo(
    session: AsyncSession = Depends(get_db_session),
) -> CollateralEscrowRepository:
    return CollateralEscrowRepository(session)


async def get_npa_repo(session: AsyncSession = Depends(get_db_session)) -> NpaEventRepository:
    return NpaEventRepository(session)


async def get_audit_repo(
    session: AsyncSession = Depends(get_db_session),
) -> AuditEventRepository:
    return AuditEventRepository(session)


async def get_idempotency_repo(
    session: AsyncSession = Depends(get_db_session),
) -> IdempotencyRepository:
    return IdempotencyRepository(session)


async def get_current_user_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization header")
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="invalid authorization format")
    return parts[1]
