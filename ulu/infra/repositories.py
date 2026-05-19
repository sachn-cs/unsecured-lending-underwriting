"""Repository pattern for database-backed domain persistence."""

from __future__ import annotations

import base64
import datetime
import json
import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ulu.errors import NotFoundError
from ulu.infra.models import (
    AmlAuditRecord,
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

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Generic base repository with common CRUD operations."""

    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self.session = session
        self.model = model

    async def create(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def bulk_create(self, entities: Sequence[T]) -> Sequence[T]:
        """Efficiently inserts multiple entities in a single round-trip."""
        self.session.add_all(entities)
        await self.session.flush()
        return entities

    async def get_by_id(self, entity_id: Any) -> T | None:
        return await self.session.get(self.model, entity_id)

    async def soft_delete(self, entity_id: Any) -> None:
        entity = await self.get_by_id(entity_id)
        if entity is not None and hasattr(entity, "deleted_at"):
            entity.deleted_at = datetime.datetime.now(datetime.timezone.utc)
            await self.session.flush()

    def _active_filter(self, stmt):
        if hasattr(self.model, "deleted_at"):
            return stmt.where(self.model.deleted_at.is_(None))
        return stmt

    @staticmethod
    def _paginate(stmt, offset: int = 0, limit: int = 100):
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit < 1:
            raise ValueError("limit must be positive")
        return stmt.offset(offset).limit(limit)

    @staticmethod
    def _encode_cursor(offset: int, limit: int) -> str:
        blob = base64.urlsafe_b64encode(
            json.dumps({"o": offset, "l": limit}).encode("utf-8")
        )
        return blob.decode("utf-8").rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str | None) -> tuple[int, int]:
        if not cursor:
            return 0, 100
        padded = cursor + "=" * (4 - len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")))
        return decoded.get("o", 0), decoded.get("l", 100)

    async def paginate_cursor(
        self,
        stmt,
        cursor: str | None = None,
        default_limit: int = 100,
    ) -> dict[str, Any]:
        """Executes a statement with cursor-based pagination and returns items + next cursor."""
        offset, limit = self._decode_cursor(cursor)
        if limit < 1 or limit > 1000:
            limit = default_limit
        paginated = stmt.offset(offset).limit(limit + 1)
        result = await self.session.execute(paginated)
        items = result.scalars().all()
        has_more = len(items) > limit
        items = items[:limit]
        next_cursor = self._encode_cursor(offset + limit, limit) if has_more else None
        return {"items": list(items), "next_cursor": next_cursor, "has_more": has_more}


class UserRepository(BaseRepository[User]):
    """Repository for User entity persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_identifier(self, identifier: str) -> User | None:
        stmt = self._active_filter(select(User).where(User.identifier == identifier))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_type(self, user_type: str, offset: int = 0, limit: int = 100) -> Sequence[User]:
        stmt = self._paginate(
            self._active_filter(select(User).where(User.user_type == user_type)), offset=offset, limit=limit
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[User]:
        stmt = self._paginate(self._active_filter(select(User)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
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


class SponsorEdgeRepository(BaseRepository[SponsorEdge]):
    """Repository for SponsorEdge persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SponsorEdge)

    async def get_by_sponsor_child(self, sponsor_id: uuid.UUID, child_id: uuid.UUID) -> SponsorEdge | None:
        stmt = self._active_filter(
            select(SponsorEdge).where(
                SponsorEdge.sponsor_id == sponsor_id,
                SponsorEdge.child_id == child_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_sponsor(self, sponsor_id: uuid.UUID, offset: int = 0, limit: int = 100) -> Sequence[SponsorEdge]:
        stmt = self._paginate(
            self._active_filter(select(SponsorEdge).where(SponsorEdge.sponsor_id == sponsor_id)),
            offset=offset,
            limit=limit,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[SponsorEdge]:
        stmt = self._paginate(self._active_filter(select(SponsorEdge)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_delegation(self, edge_id: uuid.UUID, new_amount: float) -> None:
        edge = await self.get_by_id(edge_id)
        if edge is None:
            raise NotFoundError(f"SponsorEdge {edge_id} not found for delegation update")
        edge.delegation_amount = new_amount
        await self.session.flush()


class UserBalanceRepository(BaseRepository[UserBalance]):
    """Repository for UserBalance persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UserBalance)

    async def get_by_user_id(self, user_id: uuid.UUID) -> UserBalance | None:
        return await self.get_by_id(user_id)

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[UserBalance]:
        stmt = self._paginate(self._active_filter(select(UserBalance)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_balance(
        self,
        user_id: uuid.UUID,
        base_budget: float | None = None,
        earned_credit: float | None = None,
        outstanding_principal: float | None = None,
        credit_limit: float | None = None,
    ) -> None:
        balance = await self.get_by_id(user_id)
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


class LoanRepository(BaseRepository[Loan]):
    """Repository for Loan persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Loan)

    async def list_by_borrower(self, borrower_id: uuid.UUID, offset: int = 0, limit: int = 100) -> Sequence[Loan]:
        stmt = self._paginate(
            self._active_filter(select(Loan).where(Loan.borrower_id == borrower_id)), offset=offset, limit=limit
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[Loan]:
        stmt = self._paginate(self._active_filter(select(Loan)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_status(self, loan_id: uuid.UUID, status: LoanStatus) -> None:
        loan = await self.get_by_id(loan_id)
        if loan is None:
            raise NotFoundError(f"Loan {loan_id} not found for status update")
        loan.status = status
        await self.session.flush()


class RepaymentRepository(BaseRepository[Repayment]):
    """Repository for Repayment persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Repayment)

    async def list_by_loan(self, loan_id: uuid.UUID, offset: int = 0, limit: int = 100) -> Sequence[Repayment]:
        stmt = self._paginate(
            self._active_filter(select(Repayment).where(Repayment.loan_id == loan_id)), offset=offset, limit=limit
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[Repayment]:
        stmt = self._paginate(self._active_filter(select(Repayment)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class DefaultRepository(BaseRepository[Default]):
    """Repository for Default persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Default)

    async def list_by_loan(self, loan_id: uuid.UUID, offset: int = 0, limit: int = 100) -> Sequence[Default]:
        stmt = self._paginate(
            self._active_filter(select(Default).where(Default.loan_id == loan_id)), offset=offset, limit=limit
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[Default]:
        stmt = self._paginate(self._active_filter(select(Default)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class CollateralEscrowRepository(BaseRepository[CollateralEscrow]):
    """Repository for CollateralEscrow persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CollateralEscrow)

    async def list_by_owner(self, owner_id: uuid.UUID, offset: int = 0, limit: int = 100) -> Sequence[CollateralEscrow]:
        stmt = self._paginate(
            self._active_filter(select(CollateralEscrow).where(CollateralEscrow.owner_id == owner_id)),
            offset=offset,
            limit=limit,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[CollateralEscrow]:
        stmt = self._paginate(self._active_filter(select(CollateralEscrow)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_loan(self, loan_id: uuid.UUID, offset: int = 0, limit: int = 100) -> Sequence[CollateralEscrow]:
        stmt = self._paginate(
            self._active_filter(select(CollateralEscrow).where(CollateralEscrow.loan_id == loan_id)),
            offset=offset,
            limit=limit,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_lien_status(self, escrow_id: uuid.UUID, lien_status: LienStatus) -> None:
        escrow = await self.get_by_id(escrow_id)
        if escrow is None:
            raise NotFoundError(f"CollateralEscrow {escrow_id} not found for lien status update")
        escrow.lien_status = lien_status
        await self.session.flush()


class NpaEventRepository(BaseRepository[NpaEvent]):
    """Repository for NpaEvent persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NpaEvent)

    async def get_by_loan_id(self, loan_id: uuid.UUID) -> NpaEvent | None:
        stmt = self._active_filter(select(NpaEvent).where(NpaEvent.loan_id == loan_id))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_pending_dlg(self, offset: int = 0, limit: int = 100) -> Sequence[NpaEvent]:
        stmt = self._paginate(
            self._active_filter(
                select(NpaEvent).where(
                    NpaEvent.status.in_([NpaStatus.SUBSTANDARD, NpaStatus.DOUBTFUL, NpaStatus.LOSS]),
                    NpaEvent.dlg_invoked.is_(False),
                )
            ),
            offset=offset,
            limit=limit,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[NpaEvent]:
        stmt = self._paginate(self._active_filter(select(NpaEvent)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def mark_dlg_invoked(self, event_id: uuid.UUID) -> None:
        event = await self.get_by_id(event_id)
        if event is None:
            raise NotFoundError(f"NpaEvent {event_id} not found for DLG invocation mark")
        event.dlg_invoked = True
        await self.session.flush()


class AuditEventRepository(BaseRepository[AuditEvent]):
    """Repository for AuditEvent persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditEvent)

    async def get_max_seq(self) -> int:
        result = await self.session.execute(select(func.max(AuditEvent.seq)))
        return result.scalar() or 0

    async def list_by_type(self, event_type: str, limit: int = 100, offset: int = 0) -> Sequence[AuditEvent]:
        stmt = self._active_filter(
            select(AuditEvent)
            .where(AuditEvent.event_type == event_type)
            .order_by(AuditEvent.timestamp_utc.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[AuditEvent]:
        stmt = self._paginate(self._active_filter(select(AuditEvent)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_type_cursor(self, event_type: str, cursor: str | None = None) -> dict[str, Any]:
        stmt = (
            self._active_filter(select(AuditEvent))
            .where(AuditEvent.event_type == event_type)
            .order_by(AuditEvent.timestamp_utc.desc())
        )
        return await self.paginate_cursor(stmt, cursor=cursor)


class AmlAuditRepository(BaseRepository[AmlAuditRecord]):
    """Repository for AML audit trail persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AmlAuditRecord)

    async def list_by_user(
        self,
        user_id: str,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[AmlAuditRecord]:
        stmt = self._paginate(
            self._active_filter(
                select(AmlAuditRecord)
                .where(AmlAuditRecord.user_id == user_id)
                .order_by(AmlAuditRecord.created_at.desc())
            ),
            offset=offset,
            limit=limit,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[AmlAuditRecord]:
        stmt = self._paginate(
            self._active_filter(select(AmlAuditRecord).order_by(AmlAuditRecord.created_at.desc())),
            offset=offset,
            limit=limit,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class IdempotencyRepository(BaseRepository[IdempotencyRecord]):
    """Repository for IdempotencyRecord persistence."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IdempotencyRecord)

    async def get(self, operation_name: str, idempotency_key: str) -> IdempotencyRecord | None:
        record = await self.session.get(IdempotencyRecord, (operation_name, idempotency_key))
        if record is not None and getattr(record, "deleted_at", None) is not None:
            return None
        return record

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[IdempotencyRecord]:
        stmt = self._paginate(self._active_filter(select(IdempotencyRecord)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ProtocolSnapshotRepository(BaseRepository[ProtocolSnapshot]):
    """Repository for ProtocolSnapshot persistence with optional gzip compression."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ProtocolSnapshot)

    async def create_compressed(self, state: dict, schema_version: int = 1) -> ProtocolSnapshot:
        """Creates a snapshot with gzip-compressed state payload."""
        from ulu.infra.snapshot_compression import SnapshotCompressor

        compressed = SnapshotCompressor.compress(state)
        snapshot = ProtocolSnapshot(
            schema_version=schema_version,
            state=state,
            compressed_state=compressed,
        )
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot

    @staticmethod
    def decompress_state(snapshot: ProtocolSnapshot) -> dict:
        """Returns uncompressed state from compressed payload if present."""
        if snapshot.compressed_state is not None:
            from ulu.infra.snapshot_compression import SnapshotCompressor

            return SnapshotCompressor.decompress(snapshot.compressed_state)
        return dict(snapshot.state) if snapshot.state else {}

    async def get_latest(self) -> ProtocolSnapshot | None:
        stmt = self._active_filter(select(ProtocolSnapshot).order_by(ProtocolSnapshot.taken_at.desc())).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self, offset: int = 0, limit: int = 100) -> Sequence[ProtocolSnapshot]:
        stmt = self._paginate(self._active_filter(select(ProtocolSnapshot)), offset=offset, limit=limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
