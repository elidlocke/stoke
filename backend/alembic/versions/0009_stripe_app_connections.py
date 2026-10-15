"""Stripe accounts connected by installing the Stripe App: their stored secret is an OAuth refresh token,
which has no last four characters to show.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("key_type_known", "stripe_credentials", type_="check")
    op.create_check_constraint("key_type_known", "stripe_credentials", "key_type IN ('restricted', 'secret', 'oauth')")
    op.alter_column("stripe_credentials", "key_last4", existing_type=sa.String(4), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM stripe_credentials WHERE key_type = 'oauth'")
    op.alter_column("stripe_credentials", "key_last4", existing_type=sa.String(4), nullable=False)
    op.drop_constraint("key_type_known", "stripe_credentials", type_="check")
    op.create_check_constraint("key_type_known", "stripe_credentials", "key_type IN ('restricted', 'secret')")
