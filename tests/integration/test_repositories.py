"""Integration tests for repository layer with async database."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ulu.infra.models import (
    AuditEvent,
    CollateralEscrow,
    CollateralType,
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
    RepaymentType,
    SponsorEdge,
    User,
    UserBalance,
    UserType,
)
from ulu.infra.repositories import (
    AuditEventRepository,
    CollateralEscrowRepository,
    DefaultRepository,
    IdempotencyRepository,
    LoanRepository,
    NpaEventRepository,
    ProtocolSnapshotRepository,
    RepaymentRepository,
    SponsorEdgeRepository,
    UserBalanceRepository,
    UserRepository,
)


class TestUserRepository:
    async def test_create_and_get(self, async_session: AsyncSession) -> None:
        repo = UserRepository(async_session)
        user = User(identifier="u1", user_type=UserType.BORROWER)
        created = await repo.create(user)
        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.identifier == "u1"

    async def test_get_by_identifier(self, async_session: AsyncSession) -> None:
        repo = UserRepository(async_session)
        user = User(identifier="u2", user_type=UserType.SEED)
        await repo.create(user)
        fetched = await repo.get_by_identifier("u2")
        assert fetched is not None
        assert fetched.user_type == UserType.SEED

    async def test_update_kyc(self, async_session: AsyncSession) -> None:
        repo = UserRepository(async_session)
        user = User(identifier="u3", user_type=UserType.BORROWER)
        created = await repo.create(user)
        await repo.update_kyc(created.id, KycStatus.VERIFIED)
        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.kyc_status == KycStatus.VERIFIED


class TestSponsorEdgeRepository:
    async def test_create_and_get(self, async_session: AsyncSession, seed_user: User, lsp_user: User) -> None:
        repo = SponsorEdgeRepository(async_session)
        edge = SponsorEdge(sponsor_id=seed_user.id, child_id=lsp_user.id, delegation_amount=100.0)
        await repo.create(edge)
        fetched = await repo.get_by_sponsor_child(seed_user.id, lsp_user.id)
        assert fetched is not None
        assert fetched.delegation_amount == 100.0

    async def test_update_delegation(self, async_session: AsyncSession, seed_user: User, lsp_user: User) -> None:
        repo = SponsorEdgeRepository(async_session)
        edge = SponsorEdge(sponsor_id=seed_user.id, child_id=lsp_user.id, delegation_amount=100.0)
        created = await repo.create(edge)
        await repo.update_delegation(created.id, 80.0)
        fetched = await repo.get_by_sponsor_child(seed_user.id, lsp_user.id)
        assert fetched is not None
        assert fetched.delegation_amount == 80.0


class TestUserBalanceRepository:
    async def test_create_and_update(self, async_session: AsyncSession, seed_user: User) -> None:
        repo = UserBalanceRepository(async_session)
        balance = UserBalance(user_id=seed_user.id, base_budget=1000.0, credit_limit=1000.0)
        await repo.create(balance)
        await repo.update_balance(seed_user.id, earned_credit=50.0)
        fetched = await repo.get_by_user_id(seed_user.id)
        assert fetched is not None
        assert fetched.earned_credit == 50.0


class TestLoanRepository:
    async def test_create_and_list(self, async_session: AsyncSession, borrower_user: User) -> None:
        repo = LoanRepository(async_session)
        loan = Loan(
            borrower_id=borrower_user.id,
            principal=5000.0,
            term=12.0,
            protocol_rate=0.15,
            delegation_rate=0.05,
            status=LoanStatus.ORIGINATED,
        )
        await repo.create(loan)
        loans = await repo.list_by_borrower(borrower_user.id)
        assert len(loans) == 1
        assert loans[0].principal == 5000.0

    async def test_update_status(self, async_session: AsyncSession, borrower_user: User) -> None:
        repo = LoanRepository(async_session)
        loan = Loan(
            borrower_id=borrower_user.id,
            principal=5000.0,
            term=12.0,
            protocol_rate=0.15,
            delegation_rate=0.05,
        )
        created = await repo.create(loan)
        await repo.update_status(created.id, LoanStatus.DEFAULTED)
        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.status == LoanStatus.DEFAULTED


class TestCollateralEscrowRepository:
    async def test_create_and_list(self, async_session: AsyncSession, seed_user: User) -> None:
        repo = CollateralEscrowRepository(async_session)
        escrow = CollateralEscrow(
            owner_id=seed_user.id,
            collateral_type=CollateralType.CASH_DEPOSIT,
            nominal_value=10000.0,
            effective_value=9500.0,
        )
        await repo.create(escrow)
        escrows = await repo.list_by_owner(seed_user.id)
        assert len(escrows) == 1

    async def test_update_lien_status(self, async_session: AsyncSession, seed_user: User) -> None:
        repo = CollateralEscrowRepository(async_session)
        escrow = CollateralEscrow(
            owner_id=seed_user.id,
            collateral_type=CollateralType.CASH_DEPOSIT,
            nominal_value=10000.0,
            effective_value=9500.0,
            lien_status=LienStatus.FREE,
        )
        created = await repo.create(escrow)
        await repo.update_lien_status(created.id, LienStatus.LIENED)
        fetched = await repo.get_by_id(created.id)
        assert fetched is not None
        assert fetched.lien_status == LienStatus.LIENED


class TestNpaEventRepository:
    async def test_create_and_pending(self, async_session: AsyncSession, borrower_user: User) -> None:
        repo = NpaEventRepository(async_session)
        loan = Loan(borrower_id=borrower_user.id, principal=1000.0, term=1.0, protocol_rate=0.1, delegation_rate=0.05)
        async_session.add(loan)
        await async_session.flush()
        event = NpaEvent(loan_id=loan.id, days_overdue=125, status=NpaStatus.SUBSTANDARD, dlg_invoked=False)
        await repo.create(event)
        pending = await repo.list_pending_dlg()
        assert len(pending) == 1
        await repo.mark_dlg_invoked(pending[0].id)
        pending_after = await repo.list_pending_dlg()
        assert len(pending_after) == 0


class TestAuditEventRepository:
    async def test_create_and_list(self, async_session: AsyncSession) -> None:
        repo = AuditEventRepository(async_session)
        event = AuditEvent(seq=1, event_type="test_event", payload={"key": "value"})
        await repo.create(event)
        events = await repo.list_by_type("test_event")
        assert len(events) == 1
        assert events[0].payload == {"key": "value"}

    async def test_max_seq(self, async_session: AsyncSession) -> None:
        repo = AuditEventRepository(async_session)
        assert await repo.get_max_seq() == 0
        await repo.create(AuditEvent(seq=1, event_type="a", payload={}))
        await repo.create(AuditEvent(seq=2, event_type="a", payload={}))
        assert await repo.get_max_seq() == 2


class TestIdempotencyRepository:
    async def test_create_and_get(self, async_session: AsyncSession) -> None:
        repo = IdempotencyRepository(async_session)
        record = IdempotencyRecord(
            operation_name="add_seed", idempotency_key="k1", payload_hash="h1", response={"status": "ok"}
        )
        await repo.create(record)
        fetched = await repo.get("add_seed", "k1")
        assert fetched is not None
        assert fetched.response == {"status": "ok"}


class TestProtocolSnapshotRepository:
    async def test_create_and_latest(self, async_session: AsyncSession) -> None:
        repo = ProtocolSnapshotRepository(async_session)
        snap = ProtocolSnapshot(schema_version=1, state={"seeds": ["s1"]})
        await repo.create(snap)
        latest = await repo.get_latest()
        assert latest is not None
        assert latest.state == {"seeds": ["s1"]}


class TestRepaymentRepository:
    async def test_create_and_list(self, async_session: AsyncSession, borrower_user: User) -> None:
        loan = Loan(
            borrower_id=borrower_user.id,
            principal=5000.0,
            term=12.0,
            protocol_rate=0.15,
            delegation_rate=0.05,
            status=LoanStatus.ORIGINATED,
        )
        async_session.add(loan)
        await async_session.flush()
        await async_session.refresh(loan)

        repo = RepaymentRepository(async_session)
        repayment = Repayment(
            loan_id=loan.id,
            amount=500.0,
            delta_earned=400.0,
            repayment_type=RepaymentType.SCHEDULED,
        )
        await repo.create(repayment)
        repayments = await repo.list_by_loan(loan.id)
        assert len(repayments) == 1
        assert repayments[0].amount == 500.0
        assert repayments[0].delta_earned == 400.0


class TestDefaultRepository:
    async def test_create_and_list(self, async_session: AsyncSession, borrower_user: User) -> None:
        loan = Loan(
            borrower_id=borrower_user.id,
            principal=5000.0,
            term=12.0,
            protocol_rate=0.15,
            delegation_rate=0.05,
            status=LoanStatus.ORIGINATED,
        )
        async_session.add(loan)
        await async_session.flush()
        await async_session.refresh(loan)

        repo = DefaultRepository(async_session)
        default = Default(
            loan_id=loan.id,
            default_amount=5000.0,
            logical_loss=4500.0,
            physical_recovery=225.0,
        )
        await repo.create(default)
        defaults = await repo.list_by_loan(loan.id)
        assert len(defaults) == 1
        assert defaults[0].default_amount == 5000.0
        assert defaults[0].logical_loss == 4500.0
        assert defaults[0].physical_recovery == 225.0
