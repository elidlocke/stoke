"""The writer's revenue sources and social profiles.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "writer_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("paid_via_account_id", sa.Text()),
        sa.Column("purchase", sa.Text()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("category IN ('revenue_source', 'social')", name="category_known"),
        sa.CheckConstraint("purchase IN ('once', 'repeat', 'subscription')", name="purchase_known"),
    )
    op.create_index("ix_writer_links_user_id", "writer_links", ["user_id"])


def downgrade() -> None:
    op.drop_table("writer_links")
