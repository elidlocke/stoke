"""The writer's links (revenue sources and social profiles), scoped to their owner."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import credentials
from app.actions import RevenueSource
from app.auth import CurrentUser
from app.db_models import WriterLink, credential_account_id
from app.models import LinkIn

MAX_LINKS = 50


class LinkError(Exception):
    """The link can't be saved; the message is safe to show the user."""


class LinkNotFound(Exception):
    pass


async def list_for_user(session: AsyncSession, user: CurrentUser) -> list[WriterLink]:
    return list(await session.scalars(
        select(WriterLink).where(WriterLink.user_id == user.id).order_by(WriterLink.position, WriterLink.created_at)
    ))


async def revenue_sources(session: AsyncSession, user: CurrentUser) -> list[RevenueSource]:
    """The writer's revenue sources, as the actions read them."""
    return [
        RevenueSource(
            id=str(link.id), kind=link.kind, name=link.name or link.kind, purchase=link.purchase or "once",
            paid_via_account_id=link.paid_via_account_id,
        )
        for link in await list_for_user(session, user)
        if link.category == "revenue_source"
    ]


async def get_for_user(session: AsyncSession, user: CurrentUser, link_id: uuid.UUID) -> WriterLink:
    link = await session.scalar(select(WriterLink).where(WriterLink.id == link_id, WriterLink.user_id == user.id))
    if link is None:
        raise LinkNotFound(link_id)
    return link


async def _check_account(session: AsyncSession, user: CurrentUser, account_id: str | None) -> None:
    if account_id is None:
        return
    accounts = {credential_account_id(c) for c in await credentials.list_for_user(session, user)}
    if account_id not in accounts:
        raise LinkError("That Stripe account isn't one you've added.")


def _apply(link: WriterLink, body: LinkIn) -> None:
    link.category, link.kind, link.name, link.url = body.category, body.kind, body.name, body.url
    link.paid_via_account_id, link.purchase = body.paid_via_account_id, body.purchase


async def add(session: AsyncSession, user: CurrentUser, body: LinkIn) -> WriterLink:
    count = await session.scalar(select(func.count()).where(WriterLink.user_id == user.id))
    if (count or 0) >= MAX_LINKS:
        raise LinkError(f"You can add up to {MAX_LINKS} links.")
    await _check_account(session, user, body.paid_via_account_id)
    last = await session.scalar(select(func.max(WriterLink.position)).where(WriterLink.user_id == user.id))
    link = WriterLink(user_id=user.id, position=(last or 0) + 1)
    _apply(link, body)
    session.add(link)
    await session.commit()
    return link


async def update(session: AsyncSession, user: CurrentUser, link_id: uuid.UUID, body: LinkIn) -> WriterLink:
    link = await get_for_user(session, user, link_id)
    if body.category != link.category:
        raise LinkError("A link can't move to another list.")
    await _check_account(session, user, body.paid_via_account_id)
    _apply(link, body)
    await session.commit()
    return link


async def delete(session: AsyncSession, user: CurrentUser, link_id: uuid.UUID) -> None:
    await session.delete(await get_for_user(session, user, link_id))
    await session.commit()
