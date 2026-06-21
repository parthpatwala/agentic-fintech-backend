"""initial schema: invoices and mandate_audit tables

Revision ID: 001
Revises:
Create Date: 2026-06-21

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("stripe_payment_intent_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("settled_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_invoices_status", "invoices", ["status"])

    op.create_table(
        "mandate_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "invoices.session_id", name="fk_mandate_audit_session_id"
            ),
            nullable=False,
        ),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("mandate_jwt_hash", sa.String(64), nullable=False),
        sa.Column(
            "settlement_timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_mandate_audit_session_id", "mandate_audit", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mandate_audit_session_id", table_name="mandate_audit")
    op.drop_table("mandate_audit")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_table("invoices")
