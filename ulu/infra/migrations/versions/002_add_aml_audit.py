"""Add AML audit trail table.

Revision ID: 002_add_aml_audit
Revises: 001_initial_schema
Create Date: 2026-05-19

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_add_aml_audit"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aml_audit_records",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("screen_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("status_before", sa.String(16), nullable=False),
        sa.Column("status_after", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column("payload", postgresql.JSONB, default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_aml_audit_user_id", "aml_audit_records", ["user_id"])
    op.create_index("ix_aml_audit_screen_type", "aml_audit_records", ["screen_type"])
    op.create_index("ix_aml_audit_user_time", "aml_audit_records", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_aml_audit_user_time", table_name="aml_audit_records")
    op.drop_index("ix_aml_audit_screen_type", table_name="aml_audit_records")
    op.drop_index("ix_aml_audit_user_id", table_name="aml_audit_records")
    op.drop_table("aml_audit_records")
