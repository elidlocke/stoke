"""Actions the writer has set up, and the notes sent for them.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("subject", sa.Text()),
        sa.Column("body", sa.Text()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "kind"),
    )
    op.create_index("ix_actions_user_id", "actions", ["user_id"])
    op.create_table(
        "outreach",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.Uuid(), sa.ForeignKey("actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.String(24), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("note_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("note_wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("note_cipher", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("converted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "action_id", "customer_id"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'scheduled', 'sent', 'skipped')", name="status_known"
        ),
    )
    op.create_index("ix_outreach_user_id", "outreach", ["user_id"])
    op.create_index("ix_outreach_customer_id", "outreach", ["customer_id"])


def downgrade() -> None:
    op.drop_table("outreach")
    op.drop_table("actions")
