"""Users, their settings, and their encrypted Stripe keys.

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("auth_subject", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("reporting_currency", sa.String(3)),
    )
    op.create_table(
        "stripe_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.Text()),
        sa.Column("stripe_account_id", sa.Text()),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.String(3), nullable=False),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("key_type", sa.Text(), nullable=False),
        sa.Column("key_last4", sa.String(4), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("cipher", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("missing_permissions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "stripe_account_id"),
        sa.CheckConstraint("key_type IN ('restricted', 'secret')", name="key_type_known"),
        sa.CheckConstraint("status IN ('ok', 'missing_permissions', 'invalid')", name="status_known"),
    )
    op.create_index("ix_stripe_credentials_user_id", "stripe_credentials", ["user_id"])


def downgrade() -> None:
    op.drop_table("stripe_credentials")
    op.drop_table("user_settings")
    op.drop_table("users")
