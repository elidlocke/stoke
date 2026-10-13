from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app import links, service
from app.actions import RevenueSource
from app.auth import CurrentUser, UserDep
from app.db import get_session
from app.models import ActionAudienceResponse, ActionsResponse

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _sources(session: AsyncSession, user: CurrentUser) -> list[RevenueSource]:
    return [
        RevenueSource(
            id=str(link.id), kind=link.kind, name=link.name or link.kind, purchase=link.purchase or "once",
            paid_via_account_id=link.paid_via_account_id,
        )
        for link in await links.list_for_user(session, user)
        if link.category == "revenue_source"
    ]


@router.get("/actions")
async def get_actions(
    user: UserDep, session: SessionDep, account: str | None = None, refresh: bool = False
) -> ActionsResponse:
    """The action library, with each action's audience size."""
    return await service.actions(user, await _sources(session, user), account, refresh)


@router.get("/actions/{kind}")
async def get_action(
    user: UserDep,
    session: SessionDep,
    kind: Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{0,80}$")],
    account: str | None = None,
    refresh: bool = False,
) -> ActionAudienceResponse:
    """One action's audience: who's in it, and why."""
    try:
        return await service.action(user, await _sources(session, user), kind, account, refresh)
    except service.UnknownAction:
        raise HTTPException(404, "Action not found")
