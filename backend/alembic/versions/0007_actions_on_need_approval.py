"""An action is only on while its note is approved: turn off any that were turned on without one.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE actions SET enabled = false WHERE enabled AND approved_at IS NULL")


def downgrade() -> None:
    pass  # which actions were on isn't kept; leaving them off is safe
