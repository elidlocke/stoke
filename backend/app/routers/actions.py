from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app import links, profile, service
from app.auth import UserDep
from app.db import get_session
from app.models import ActionAudienceResponse, ActionsResponse

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/actions")
async def get_actions(
    user: UserDep, session: SessionDep, account: str | None = None, refresh: bool = False
) -> ActionsResponse:
    """The action library, with each action's audience size."""
    sources, labels = await links.revenue_sources(session, user), await profile.labels(session, user)
    return await service.actions(user, sources, labels, account, refresh)


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
        sources, labels = await links.revenue_sources(session, user), await profile.labels(session, user)
        return await service.action(user, sources, labels, kind, account, refresh)
    except service.UnknownAction:
        raise HTTPException(404, "Action not found")
