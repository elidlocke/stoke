"""Stored Stripe objects, kept current by webhooks and the Events API.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "stripe_accounts",
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column("livemode", sa.Boolean(), primary_key=True),
        sa.Column("active_version", sa.Text(), nullable=False),
        sa.Column("target_version", sa.Text()),
        sa.Column("backfilled_at", TS),
        sa.Column("events_cursor", TS, nullable=False),
        sa.Column("key_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("key_cipher", sa.Text(), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "stripe_objects",
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column("livemode", sa.Boolean(), primary_key=True),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("object", sa.Text(), primary_key=True),
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("created", TS),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", TS, nullable=False),
        sa.CheckConstraint("object IN ('payment_intent', 'invoice', 'subscription', 'customer')", name="object_known"),
    )
    op.create_index(
        "ix_stripe_objects_created", "stripe_objects", ["account_id", "livemode", "version", "object", "created"]
    )
    op.create_table(
        "stripe_sync_queue",
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column("livemode", sa.Boolean(), primary_key=True),
        sa.Column("object", sa.Text(), primary_key=True),
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("enqueued_at", TS, nullable=False),
        sa.Column("claimed_at", TS),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "stripe_backfills",
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column("livemode", sa.Boolean(), primary_key=True),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("object", sa.Text(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("starting_after", sa.Text()),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("retry_at", TS),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("heartbeat_at", TS),
        sa.CheckConstraint("state IN ('pending', 'running', 'done', 'skipped', 'failed')", name="state_known"),
    )


def downgrade() -> None:
    op.drop_table("stripe_backfills")
    op.drop_table("stripe_sync_queue")
    op.drop_table("stripe_objects")
    op.drop_table("stripe_accounts")
