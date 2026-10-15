"""The writer's free subscribers, uploaded from each publication's Substack export, for the Free -> paid action.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COUNTS = (
    "activity", "emails_received_6mo", "emails_opened_6mo", "days_active_30d", "post_views_30d", "links_clicked",
    "comments", "shares",
)


def upgrade() -> None:
    op.create_table(
        "substack_lists",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("publication", sa.Text(), primary_key=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("free_count", sa.Integer(), nullable=False),
        sa.Column("key_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("key_cipher", sa.Text(), nullable=False),
    )
    op.create_table(
        "substack_subscribers",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("publication", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.String(24), primary_key=True),
        sa.Column("email", sa.LargeBinary(), nullable=False),
        sa.Column("first_name", sa.LargeBinary(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        *(sa.Column(c, sa.Integer(), nullable=False, server_default="0") for c in _COUNTS),
        sa.ForeignKeyConstraint(
            ["user_id", "publication"], ["substack_lists.user_id", "substack_lists.publication"], ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("substack_subscribers")
    op.drop_table("substack_lists")
