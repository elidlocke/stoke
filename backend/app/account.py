"""Deleting a writer's account and everything Stoke holds for them."""

from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app import credentials, gmail, substack_list
from app.auth import CurrentUser
from app.db_models import User


async def delete(session: AsyncSession, user: CurrentUser) -> None:
    """Revokes Gmail at Google (best effort), removes each Stripe connection the way Settings does, so stored
    customer data goes too once nobody else has the account connected, then deletes the user. Their settings,
    links, actions, notes and Substack lists go with the user row (ON DELETE CASCADE).

    The Auth0 identity stays: signing in again starts a new, empty account."""
    await gmail.disconnect(session, user)
    for cred in await credentials.list_for_user(session, user):
        await credentials.delete(session, user, cred.id)
    await session.execute(sql_delete(User).where(User.id == user.id))
    await session.commit()
    substack_list.forget_user(user.id)
