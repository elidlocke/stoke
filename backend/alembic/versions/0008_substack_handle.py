"""The writer's Substack handle, read for the links on their public profile.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_settings", sa.Column("substack_handle", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_settings", "substack_handle")
