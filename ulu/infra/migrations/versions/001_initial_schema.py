"""Initial schema for production middleware.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-05-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _kyc = sa.Enum("pending", "verified", "rejected", "expired", name="kycstatus")
    _aml = sa.Enum("clear", "flagged", "frozen", name="amlstatus")
    _loan = sa.Enum(
        "originated", "active", "overdue", "defaulted", "recovered", "written_off",
        name="loanstatus",
    )
    _repay = sa.Enum("scheduled", "prepayment", "partial", name="repaymenttype")
    _coll = sa.Enum(
        "cash_deposit", "lien_marked_fd", "bank_guarantee", "security",
        name="collateraltype",
    )
    _lien = sa.Enum("free", "liened", "liquidated", name="lienstatus")
    _npa = sa.Enum(
        "standard", "npa", "substandard", "doubtful", "loss",
        name="npastatus",
    )

    op.create_table(
        "users",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("identifier", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "user_type",
            sa.Enum("seed", "lsp", "sub_sponsor", "borrower", name="usertype"),
            nullable=False,
        ),
        sa.Column("kyc_status", _kyc, default="pending"),
        sa.Column("aml_status", _aml, default="clear"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_identifier", "users", ["identifier"])
    op.create_index("ix_users_user_type", "users", ["user_type"])
    op.create_index("ix_users_kyc_status", "users", ["kyc_status"])
    op.create_index("ix_users_aml_status", "users", ["aml_status"])

    op.create_table(
        "sponsor_edges",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("sponsor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("child_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delegation_amount", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("sponsor_id", "child_id", name="uq_sponsor_child"),
    )
    op.create_index("ix_sponsor_edges_sponsor_child", "sponsor_edges", ["sponsor_id", "child_id"])

    op.create_table(
        "user_balances",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("base_budget", sa.Float, default=0.0),
        sa.Column("earned_credit", sa.Float, default=0.0),
        sa.Column("outstanding_principal", sa.Float, default=0.0),
        sa.Column("credit_limit", sa.Float, default=0.0),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "loans",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("principal", sa.Float, nullable=False),
        sa.Column("term", sa.Float, nullable=False),
        sa.Column("protocol_rate", sa.Float, nullable=False),
        sa.Column("delegation_rate", sa.Float, nullable=False),
        sa.Column("status", _loan, default="originated"),
        sa.Column("originated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("matured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_loans_borrower_id", "loans", ["borrower_id"])
    op.create_index("ix_loans_status", "loans", ["status"])
    op.create_index("ix_loans_borrower_status", "loans", ["borrower_id", "status"])

    op.create_table(
        "repayments",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("loan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("loans.id"), nullable=False),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("delta_earned", sa.Float, default=0.0),
        sa.Column("repayment_type", _repay, default="scheduled"),
        sa.Column("repaid_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_repayments_loan_id", "repayments", ["loan_id"])
    op.create_index("ix_repayments_repaid_at", "repayments", ["repaid_at"])

    op.create_table(
        "defaults",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("loan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("loans.id"), nullable=False),
        sa.Column("default_amount", sa.Float, nullable=False),
        sa.Column("logical_loss", sa.Float, nullable=False),
        sa.Column("physical_recovery", sa.Float, default=0.0),
        sa.Column("defaulted_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_defaults_loan_id", "defaults", ["loan_id"])
    op.create_index("ix_defaults_defaulted_at", "defaults", ["defaulted_at"])

    op.create_table(
        "collateral_escrows",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("collateral_type", _coll, nullable=False),
        sa.Column("nominal_value", sa.Float, nullable=False),
        sa.Column("haircut", sa.Float, default=0.0),
        sa.Column("effective_value", sa.Float, nullable=False),
        sa.Column("lien_status", _lien, default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_collateral_escrows_owner_id", "collateral_escrows", ["owner_id"])
    op.create_index("ix_collateral_escrows_owner_type", "collateral_escrows", ["owner_id", "collateral_type"])
    op.create_index("ix_collateral_escrows_lien_status", "collateral_escrows", ["lien_status"])

    op.create_table(
        "npa_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("loan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("loans.id"), nullable=False),
        sa.Column("days_overdue", sa.Integer, default=0),
        sa.Column("status", _npa, default="standard"),
        sa.Column("dlg_invoked", sa.Boolean, default=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_npa_events_loan_id", "npa_events", ["loan_id"])
    op.create_index("ix_npa_events_status", "npa_events", ["status"])
    op.create_index("ix_npa_events_days_overdue", "npa_events", ["days_overdue"])
    op.create_index(
        "ix_npa_events_dlg_pending",
        "npa_events",
        ["status", "dlg_invoked"],
        postgresql_where=sa.text("dlg_invoked = false"),
    )

    op.create_table(
        "audit_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, default=dict),
        sa.Column("timestamp_utc", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("merkle_root", sa.String(128), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_audit_events_seq", "audit_events", ["seq"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_type_time", "audit_events", ["event_type", "timestamp_utc"])

    op.create_table(
        "idempotency_records",
        sa.Column("operation_name", sa.String(64), nullable=False, primary_key=True),
        sa.Column("idempotency_key", sa.String(256), nullable=False, primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "protocol_snapshots",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("schema_version", sa.Integer, nullable=False, default=1),
        sa.Column("state", postgresql.JSONB, default=dict),
        sa.Column("compressed_state", sa.LargeBinary, nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("protocol_snapshots")
    op.drop_table("idempotency_records")
    op.drop_index("ix_audit_events_type_time", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_seq", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_npa_events_dlg_pending", table_name="npa_events")
    op.drop_index("ix_npa_events_days_overdue", table_name="npa_events")
    op.drop_index("ix_npa_events_status", table_name="npa_events")
    op.drop_index("ix_npa_events_loan_id", table_name="npa_events")
    op.drop_table("npa_events")
    op.drop_index("ix_collateral_escrows_lien_status", table_name="collateral_escrows")
    op.drop_index("ix_collateral_escrows_owner_type", table_name="collateral_escrows")
    op.drop_index("ix_collateral_escrows_owner_id", table_name="collateral_escrows")
    op.drop_table("collateral_escrows")
    op.drop_index("ix_defaults_defaulted_at", table_name="defaults")
    op.drop_index("ix_defaults_loan_id", table_name="defaults")
    op.drop_table("defaults")
    op.drop_index("ix_repayments_repaid_at", table_name="repayments")
    op.drop_index("ix_repayments_loan_id", table_name="repayments")
    op.drop_table("repayments")
    op.drop_index("ix_loans_borrower_status", table_name="loans")
    op.drop_index("ix_loans_status", table_name="loans")
    op.drop_index("ix_loans_borrower_id", table_name="loans")
    op.drop_table("loans")
    op.drop_table("user_balances")
    op.drop_index("ix_sponsor_edges_sponsor_child", table_name="sponsor_edges")
    op.drop_table("sponsor_edges")
    op.drop_index("ix_users_aml_status", table_name="users")
    op.drop_index("ix_users_kyc_status", table_name="users")
    op.drop_index("ix_users_user_type", table_name="users")
    op.drop_index("ix_users_identifier", table_name="users")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS usertype")
    op.execute("DROP TYPE IF EXISTS kycstatus")
    op.execute("DROP TYPE IF EXISTS amlstatus")
    op.execute("DROP TYPE IF EXISTS loanstatus")
    op.execute("DROP TYPE IF EXISTS repaymenttype")
    op.execute("DROP TYPE IF EXISTS defaulttype")
    op.execute("DROP TYPE IF EXISTS collateraltype")
    op.execute("DROP TYPE IF EXISTS lienstatus")
    op.execute("DROP TYPE IF EXISTS npastatus")
    op.execute("DROP TYPE IF EXISTS recoverytype")
