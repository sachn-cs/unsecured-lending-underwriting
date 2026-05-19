"""SQLAlchemy 2.0 declarative ORM models for the production middleware."""

from __future__ import annotations

import datetime
import enum
import uuid

import sqlalchemy as sa
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ulu.infra.db import Base


class SoftDeleteMixin:
    """Mixin adding soft-delete support via deleted_at timestamp."""

    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class UserType(enum.Enum):
    SEED = "seed"
    LSP = "lsp"
    SUB_SPONSOR = "sub_sponsor"
    BORROWER = "borrower"


class KycStatus(enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"


class AmlStatus(enum.Enum):
    CLEAR = "clear"
    FLAGGED = "flagged"
    FROZEN = "frozen"


class LoanStatus(enum.Enum):
    ORIGINATED = "originated"
    ACTIVE = "active"
    OVERDUE = "overdue"
    DEFAULTED = "defaulted"
    RECOVERED = "recovered"
    WRITTEN_OFF = "written_off"


class RepaymentType(enum.Enum):
    SCHEDULED = "scheduled"
    PREPAYMENT = "prepayment"
    PARTIAL = "partial"


class DefaultType(enum.Enum):
    FULL = "full"
    PARTIAL = "partial"


class CollateralType(enum.Enum):
    CASH_DEPOSIT = "cash_deposit"
    LIEN_MARKED_FD = "lien_marked_fd"
    BANK_GUARANTEE = "bank_guarantee"
    SECURITY = "security"


class LienStatus(enum.Enum):
    FREE = "free"
    LIENED = "liened"
    LIQUIDATED = "liquidated"


class NpaStatus(enum.Enum):
    STANDARD = "standard"
    NPA = "npa"
    SUBSTANDARD = "substandard"
    DOUBTFUL = "doubtful"
    LOSS = "loss"


class RecoveryType(enum.Enum):
    WORKOUT = "workout"
    RESTRUCTURE = "restructure"
    LIQUIDATION = "liquidation"
    WRITE_OFF = "write_off"


class User(SoftDeleteMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identifier: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_type: Mapped[UserType] = mapped_column(Enum(UserType), nullable=False, index=True)
    kyc_status: Mapped[KycStatus] = mapped_column(Enum(KycStatus), default=KycStatus.PENDING, index=True)
    aml_status: Mapped[AmlStatus] = mapped_column(Enum(AmlStatus), default=AmlStatus.CLEAR, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    balance: Mapped[UserBalance | None] = relationship("UserBalance", back_populates="user", uselist=False)
    outgoing_edges: Mapped[list[SponsorEdge]] = relationship(
        "SponsorEdge", foreign_keys="SponsorEdge.sponsor_id", back_populates="sponsor"
    )
    incoming_edges: Mapped[list[SponsorEdge]] = relationship(
        "SponsorEdge", foreign_keys="SponsorEdge.child_id", back_populates="child"
    )
    loans: Mapped[list[Loan]] = relationship("Loan", back_populates="borrower")
    collateral: Mapped[list[CollateralEscrow]] = relationship("CollateralEscrow", back_populates="owner")


class SponsorEdge(SoftDeleteMixin, Base):
    __tablename__ = "sponsor_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sponsor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    child_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    delegation_amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    sponsor: Mapped[User] = relationship("User", foreign_keys=[sponsor_id], back_populates="outgoing_edges")
    child: Mapped[User] = relationship("User", foreign_keys=[child_id], back_populates="incoming_edges")

    __table_args__ = (
        UniqueConstraint("sponsor_id", "child_id", name="uq_sponsor_child"),
        Index("ix_sponsor_edges_sponsor_child", "sponsor_id", "child_id"),
    )


class UserBalance(SoftDeleteMixin, Base):
    __tablename__ = "user_balances"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    base_budget: Mapped[float] = mapped_column(Float, default=0.0)
    earned_credit: Mapped[float] = mapped_column(Float, default=0.0)
    outstanding_principal: Mapped[float] = mapped_column(Float, default=0.0)
    credit_limit: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    user: Mapped[User] = relationship("User", back_populates="balance")


class Loan(SoftDeleteMixin, Base):
    __tablename__ = "loans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    borrower_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    principal: Mapped[float] = mapped_column(Float, nullable=False)
    term: Mapped[float] = mapped_column(Float, nullable=False)
    protocol_rate: Mapped[float] = mapped_column(Float, nullable=False)
    delegation_rate: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[LoanStatus] = mapped_column(Enum(LoanStatus), default=LoanStatus.ORIGINATED, index=True)
    originated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    matured_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    borrower: Mapped[User] = relationship("User", back_populates="loans")
    repayments: Mapped[list[Repayment]] = relationship("Repayment", back_populates="loan")
    defaults: Mapped[list[Default]] = relationship("Default", back_populates="loan")
    npa_events: Mapped[list[NpaEvent]] = relationship("NpaEvent", back_populates="loan")

    __table_args__ = (Index("ix_loans_borrower_status", "borrower_id", "status"),)


class Repayment(SoftDeleteMixin, Base):
    __tablename__ = "repayments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    delta_earned: Mapped[float] = mapped_column(Float, default=0.0)
    repayment_type: Mapped[RepaymentType] = mapped_column(Enum(RepaymentType), default=RepaymentType.SCHEDULED)
    repaid_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    loan: Mapped[Loan] = relationship("Loan", back_populates="repayments")


class Default(SoftDeleteMixin, Base):
    __tablename__ = "defaults"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False, index=True)
    default_amount: Mapped[float] = mapped_column(Float, nullable=False)
    logical_loss: Mapped[float] = mapped_column(Float, nullable=False)
    physical_recovery: Mapped[float] = mapped_column(Float, default=0.0)
    defaulted_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    loan: Mapped[Loan] = relationship("Loan", back_populates="defaults")


class CollateralEscrow(SoftDeleteMixin, Base):
    __tablename__ = "collateral_escrows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    collateral_type: Mapped[CollateralType] = mapped_column(Enum(CollateralType), nullable=False)
    nominal_value: Mapped[float] = mapped_column(Float, nullable=False)
    haircut: Mapped[float] = mapped_column(Float, default=0.0)
    effective_value: Mapped[float] = mapped_column(Float, nullable=False)
    lien_status: Mapped[LienStatus] = mapped_column(Enum(LienStatus), default=LienStatus.FREE, index=True)
    loan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("loans.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    owner: Mapped[User] = relationship("User", back_populates="collateral")

    __table_args__ = (
        Index("ix_collateral_escrows_owner_type", "owner_id", "collateral_type"),
        Index("ix_collateral_escrows_loan", "loan_id"),
    )


class NpaEvent(SoftDeleteMixin, Base):
    __tablename__ = "npa_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("loans.id"), nullable=False, index=True)
    days_overdue: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[NpaStatus] = mapped_column(Enum(NpaStatus), default=NpaStatus.STANDARD, index=True)
    dlg_invoked: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    loan: Mapped[Loan] = relationship("Loan", back_populates="npa_events")

    __table_args__ = (
        Index(
            "ix_npa_events_dlg_pending",
            "status",
            "dlg_invoked",
            postgresql_where="dlg_invoked = false",
        ),
    )


class AuditEvent(SoftDeleteMixin, Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp_utc: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    merkle_root: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (Index("ix_audit_events_type_time", "event_type", "timestamp_utc"),)


class IdempotencyRecord(SoftDeleteMixin, Base):
    __tablename__ = "idempotency_records"

    operation_name: Mapped[str] = mapped_column(String(64), nullable=False, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AmlAuditRecord(SoftDeleteMixin, Base):
    """Immutable audit trail for AML screening events."""

    __tablename__ = "aml_audit_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    screen_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    status_before: Mapped[str] = mapped_column(String(16), nullable=False)
    status_after: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(256), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_aml_audit_user_time", "user_id", "created_at"),)


class ProtocolSnapshot(SoftDeleteMixin, Base):
    __tablename__ = "protocol_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    compressed_state: Mapped[bytes | None] = mapped_column(
        sa.LargeBinary, nullable=True,
    )
    taken_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
