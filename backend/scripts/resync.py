"""Import every account again at the current API version and projection, after changing either.

Run after deploying a change to STRIPE_API_VERSION (app/stripe_client.py) or PROJECTION_REV
(app/projection.py):

    cd backend
    uv run python scripts/resync.py

Each account is imported in the background by the running app's sync worker, alongside what's
stored now. Views keep reading the current data until an account's import finishes; then it
switches over and the old data is deleted. Run it again to see which accounts are still pending.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import db, sync  # noqa: E402
from app.db_models import StripeAccount  # noqa: E402


async def main() -> int:
    async with db.sessionmaker()() as session:
        rows = list(await session.scalars(select(StripeAccount).where(StripeAccount.active_version != sync.SYNC_VERSION)))
    if not rows:
        print(f"Every account is at {sync.SYNC_VERSION}.")
    for row in rows:
        account = await sync.account_for(row.account_id, row.livemode)
        if account is None:
            print(f"{row.account_id}: no usable key; skipped.")
            continue
        await sync.start_backfill(row.account_id, row.livemode, account.missing_permissions, version=sync.SYNC_VERSION)
        print(f"{row.account_id}: importing at {sync.SYNC_VERSION} (now {row.active_version}).")
    await db.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
