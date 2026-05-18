"""Repository pattern for database-backed domain persistence."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ulu.errors import NotFoundError
from ulu.infra.models import (
    AmlStatus,
    AuditEvent,
    CollateralEscrow,
    Default,
    IdempotencyRecord,
    KycStatus,
    LienStatus,
    Loan,
    LoanStatus,
    NpaEvent,
    NpaStatus,
    ProtocolSnapshot,
    Repayment,
    SponsorEdge,
    User,
    UserBalance,
)


class UserRepository:
    """Repository for User entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_identifier(self, identifier: str) -> User | None:
        result = await self.session.execute(select(User).where(User.identifier == identifier))
        return result.scalar_one_or_none()

    async def list_by_type(self, user_type: str) -> Sequence[User]:
        result = await self.session.execute(select(User).where(User.user_type == user_type))
        return result.scalars().all()

    async def update_kyc(self, user_id: uuid.UUID, kyc_status: KycStatus) -> None:
        user = await self.get_by_id(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found for KYC update")
        user.kyc_status = kyc_status
        await self.session.flush()

    async def update_aml(self, user_id: uuid.UUID, aml_status: AmlStatus) -> None:
        user = await self.get_by_id(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} not found for AML update")
        user.aml_status = aml_status
        await self.session.flush()


class SponsorEdgeRepository:
    """Repository for SponsorEdge persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, edge: SponsorEdge) -> SponsorEdge:
        self.session.add(edge)
        await self.session.flush()
        await self.session.refresh(edge)
        return edge

    async def get_by_sponsor_child(self, sponsor_id: uuid.UUID, child_id: uuid.UUID) -> SponsorEdge | None:
        result = await self.session.execute(
            select(SponsorEdge).where(
                SponsorEdge.sponsor_id == sponsor_id,
                SponsorEdge.child_id == child_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_sponsor(self, sponsor_id: uuid.UUID) -> Sequence[SponsorEdge]:
        result = await self.session.execute(select(SponsorEdge).where(SponsorEdge.sponsor_id == sponsor_id))
        return result.scalars().all()

    async def update_delegation(self, edge_id: uuid.UUID, new_amount: float) -> None:
        edge = await self.session.get(SponsorEdge, edge_id)
        if edge is None:
            raise NotFoundError(f"SponsorEdge {edge_id} not found for delegation update")
        edge.delegation_amount = new_amount
        await self.session.flush()


class UserBalanceRepository:
    """Repository for UserBalance persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, balance: UserBalance) -> UserBalance:
        self.session.add(balance)
        await self.session.flush()
        await self.session.refresh(balance)
        return balance

    async def get_by_user_id(self, user_id: uuid.UUID) -> UserBalance | None:
        return await self.session.get(UserBalance, user_id)

    async def update_balance(
        self,
        user_id: uuid.UUID,
        base_budget: float | None = None,
        earned_credit: float | None = None,
        outstanding_principal: float | None = None,
        credit_limit: float | None = None,
    ) -> None:
        balance = await self.get_by_user_id(user_id)
        if balance is None:
            raise NotFoundError(f"UserBalance for {user_id} not found for update")
        if base_budget is not None:
            balance.base_budget = base_budget
        if earned_credit is not None:
            balance.earned_credit = earned_credit
        if outstanding_principal is not None:
            balance.outstanding_principal = outstanding_principal
        if credit_limit is not None:
            balance.credit_limit = credit_limit
        await self.session.flush()


class LoanRepository:
    """Repository for Loan persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, loan: Loan) -> Loan:
        self.session.add(loan)
        await self.session.flush()
        await self.session.refresh(loan)
        return loan

    async def get_by_id(self, loan_id: uuid.UUID) -> Loan | None:
        return await self.session.get(Loan, loan_id)

    async def list_by_borrower(self, borrower_id: uuid.UUID) -> Sequence[Loan]:
        result = await self.session.execute(select(Loan).where(Loan.borrower_id == borrower_id))
        return result.scalars().all()

    async def update_status(self, loan_id: uuid.UUID, status: LoanStatus) -> None:
        loan = await self.get_by_id(loan_id)
        if loan is None:
            raise NotFoundError(f"Loan {loan_id} not found for status update")
        loan.status = status
        await self.session.flush()


class RepaymentRepository:
    """Repository for Repayment persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, repayment: Repayment) -> Repayment:
        self.session.add(repayment)
        await self.session.flush()
        await self.session.refresh(repayment)
        return repayment

    async def list_by_loan(self, loan_id: uuid.UUID) -> Sequence[Repayment]:
        result = await self.session.execute(select(Repayment).where(Repayment.loan_id == loan_id))
        return result.scalars().all()


class DefaultRepository:
    """Repository for Default persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, default: Default) -> Default:
        self.session.add(default)
        await self.session.flush()
        await self.session.refresh(default)
        return default

    async def list_by_loan(self, loan_id: uuid.UUID) -> Sequence[Default]:
        result = await self.session.execute(select(Default).where(Default.loan_id == loan_id))
        return result.scalars().all()


class CollateralEscrowRepository:
    """Repository for CollateralEscrow persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, escrow: CollateralEscrow) -> CollateralEscrow:
        self.session.add(escrow)
        await self.session.flush()
        await self.session.refresh(escrow)
        return escrow

    async def get_by_id(self, escrow_id: uuid.UUID) -> CollateralEscrow | None:
        return await self.session.get(CollateralEscrow, escrow_id)

    async def list_by_owner(self, owner_id: uuid.UUID) -> Sequence[CollateralEscrow]:
        result = await self.session.execute(select(CollateralEscrow).where(CollateralEscrow.owner_id == owner_id))
        return result.scalars().all()

    async def update_lien_status(self, escrow_id: uuid.UUID, lien_status: LienStatus) -> None:
        escrow = await self.get_by_id(escrow_id)
        if escrow is None:
            raise NotFoundError(f"CollateralEscrow {escrow_id} not found for lien status update")
        escrow.lien_status = lien_status
        await self.session.flush()


class NpaEventRepository:
    """Repository for NpaEvent persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, event: NpaEvent) -> NpaEvent:
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def get_by_loan_id(self, loan_id: uuid.UUID) -> NpaEvent | None:
        result = await self.session.execute(select(NpaEvent).where(NpaEvent.loan_id == loan_id))
        return result.scalar_one_or_none()

    async def list_pending_dlg(self) -> Sequence[NpaEvent]:
        result = await self.session.execute(
            select(NpaEvent).where(
                NpaEvent.status.in_([NpaStatus.SUBSTANDARD, NpaStatus.DOUBTFUL, NpaStatus.LOSS]),
                NpaEvent.dlg_invoked.is_(False),
            )
        )
        return result.scalars().all()

    async def mark_dlg_invoked(self, event_id: uuid.UUID) -> None:
        event = await self.session.get(NpaEvent, event_id)
        if event is None:
            raise NotFoundError(f"NpaEvent {event_id} not found for DLG invocation mark")
        event.dlg_invoked = True
        await self.session.flush()


class AuditEventRepository:
    """Repository for AuditEvent persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, event: AuditEvent) -> AuditEvent:
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def get_max_seq(self) -> int:
        result = await self.session.execute(select(func.max(AuditEvent.seq)))
        return result.scalar() or 0

    async def list_by_type(self, event_type: str, limit: int = 100) -> Sequence[AuditEvent]:
        result = await self.session.execute(
            select(AuditEvent)
            .where(AuditEvent.event_type == event_type)
            .order_by(AuditEvent.timestamp_utc.desc())
            .limit(limit)
        )
        return result.scalars().all()


class IdempotencyRepository:
    """Repository for IdempotencyRecord persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, operation_name: str, idempotency_key: str) -> IdempotencyRecord | None:
        return await self.session.get(IdempotencyRecord, (operation_name, idempotency_key))

    async def create(self, record: IdempotencyRecord) -> IdempotencyRecord:
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record


class ProtocolSnapshotRepository:
    """Repository for ProtocolSnapshot persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, snapshot: ProtocolSnapshot) -> ProtocolSnapshot:
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot

    async def get_latest(self) -> ProtocolSnapshot | None:
        result = await self.session.execute(
            select(ProtocolSnapshot).order_by(ProtocolSnapshot.taken_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()
