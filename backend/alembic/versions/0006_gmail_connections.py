"""The writer's Gmail connection (an encrypted refresh token), and the Gmail ids of notes sent through it.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gmail_connections",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("cipher", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('ok', 'revoked')", name="gmail_status_known"),
    )
    op.add_column("outreach", sa.Column("gmail_message_id", sa.Text()))
    op.add_column("outreach", sa.Column("gmail_thread_id", sa.Text()))


def downgrade() -> None:
    op.drop_column("outreach", "gmail_thread_id")
    op.drop_column("outreach", "gmail_message_id")
    op.drop_table("gmail_connections")
