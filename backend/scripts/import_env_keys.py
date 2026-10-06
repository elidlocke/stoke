"""One-off move of the Stripe keys in .env into a user's encrypted key store.

Imports STRIPE_ACCOUNT_KEYS, and STRIPE_API_KEY / STRIPE_PLATFORM_KEY (which earlier versions used
for a single personal key) as that account's own key.

Each key goes through the same checks as the Settings page. The user must have signed in once, so
their account exists:

    cd backend
    uv run python scripts/import_env_keys.py --email you@example.com

Then delete those settings from .env.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import credentials, db  # noqa: E402
from app.auth import CurrentUser  # noqa: E402
from app.db_models import User  # noqa: E402


async def main(email: str | None, subject: str | None) -> int:
    names = ["STRIPE_ACCOUNT_KEYS", "STRIPE_PLATFORM_KEY", "STRIPE_API_KEY"]
    keys = list(dict.fromkeys(k.strip() for n in names for k in os.environ.get(n, "").split(",") if k.strip()))
    if not keys:
        print(f"None of {', '.join(names)} is set in .env; nothing to import.")
        return 0

    async with db.sessionmaker()() as session:
        q = select(User).where(User.auth_subject == subject) if subject else select(User).where(User.email == email.lower())
        users = list(await session.scalars(q))
        if len(users) != 1:
            print(f"Found {len(users)} users matching; sign in once first, or pass --subject (the Auth0 user id).")
            return 1
        user = CurrentUser(id=users[0].id, auth_subject=users[0].auth_subject, email=users[0].email)

        failed = 0
        for i, key in enumerate(keys, start=1):
            try:
                cred = await credentials.add(session, user, key)
            except credentials.CredentialError as exc:
                failed += 1
                print(f"Key #{i} (…{key[-4:]}): not imported. {exc}")
            else:
                note = f", missing {', '.join(cred.missing_permissions)}" if cred.missing_permissions else ""
                print(f"Key #{i} (…{cred.key_last4}): imported as {cred.display_name}{note}")
    await db.dispose()

    if not failed:
        print(f"\nDone. Now delete {', '.join(n for n in names if os.environ.get(n))} from .env.")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", help="the user's email, as Auth0 reports it")
    who.add_argument("--subject", help="the user's Auth0 id, e.g. auth0|abc123")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.email, args.subject)))
