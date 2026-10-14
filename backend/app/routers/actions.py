import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import links, outreach, profile, service
from app.auth import CurrentUser, UserDep
from app.db import get_session
from app.db_models import Outreach
from app.models import (
    ActionAudienceResponse,
    ActionsResponse,
    ActionUpdate,
    ContactedOut,
    ContactedResponse,
    OutreachIn,
    OutreachOut,
    OutreachResponse,
    PreviewIn,
    PreviewResponse,
    QueueResponse,
)

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
KindPath = Annotated[str, Path(pattern=r"^[a-z][a-z0-9-]{0,80}$")]
CustomerPath = Annotated[str, Path(pattern=r"^[0-9a-f]{24}$")]


async def _writer(session: AsyncSession, user: CurrentUser) -> service.Writer:
    t = await outreach.tally(session, user)
    return service.Writer(
        sources=await links.revenue_sources(session, user),
        labels=await profile.labels(session, user),
        socials=await links.socials(session, user),
        settings=await outreach.settings(session, user),
        sent=t.sent,
        last_sent=t.last_sent,
        marked=t.marked,
    )


async def _known(user: CurrentUser, w: service.Writer, kind: str) -> None:
    if kind not in service.titles(w):
        raise HTTPException(404, "Action not found")


@router.get("/actions")
async def get_actions(
    user: UserDep, session: SessionDep, account: str | None = None, refresh: bool = False
) -> ActionsResponse:
    """The action library, with each action's audience size, whether it's on, and notes sent."""
    return await service.actions(user, await _writer(session, user), account, refresh)


@router.get("/actions/{kind}")
async def get_action(
    user: UserDep, session: SessionDep, kind: KindPath, account: str | None = None, refresh: bool = False
) -> ActionAudienceResponse:
    """One action's audience (who's in it, and why) and its note template."""
    try:
        return await service.action(user, await _writer(session, user), kind, account, refresh)
    except service.UnknownAction:
        raise HTTPException(404, "Action not found")


@router.patch("/actions/{kind}", status_code=204)
async def update_action(kind: KindPath, body: ActionUpdate, user: UserDep, session: SessionDep) -> Response:
    """Turn an action on or off, edit its template, or approve it."""
    await _known(user, await _writer(session, user), kind)
    await outreach.update(
        session, user, kind, enabled=body.enabled, subject=body.subject, body=body.body, approved=body.approved,
    )
    return Response(status_code=204)


@router.get("/actions/{kind}/queue")
async def get_queue(user: UserDep, session: SessionDep, kind: KindPath, account: str | None = None) -> QueueResponse:
    """Who's left to contact for the action, each with their note filled in."""
    done = {o.customer_id for o, _ in await outreach.history(session, user, kind=kind)}
    try:
        return await service.queue(user, await _writer(session, user), kind, done, account)
    except service.UnknownAction:
        raise HTTPException(404, "Action not found")


@router.post("/actions/{kind}/preview")
async def preview_note(
    kind: KindPath, body: PreviewIn, user: UserDep, session: SessionDep, account: str | None = None
) -> PreviewResponse:
    """A draft note filled in for a few people in the action's audience, before it's saved or approved."""
    try:
        return await service.preview(user, await _writer(session, user), kind, body.subject, body.body, account)
    except service.UnknownAction:
        raise HTTPException(404, "Action not found")


@router.post("/actions/{kind}/outreach", status_code=201)
async def add_outreach(kind: KindPath, body: OutreachIn, user: UserDep, session: SessionDep) -> OutreachOut:
    """Mark someone in the queue as sent (the writer sent the note themselves) or skipped."""
    w = await _writer(session, user)
    await _known(user, w, kind)
    row = w.settings.get(kind)
    if row is None or not row.enabled or row.approved_at is None:
        raise outreach.OutreachError("Turn the action on and approve its template first.")
    if not await service.in_audience(user, w, kind, body.customer_id):
        raise outreach.OutreachError("They're not in this action's audience.")
    o = await outreach.record(session, user, row, body.customer_id, body.status, body.subject, body.body)
    await session.refresh(o)
    emails = await service.emails_by_id(user)
    return _outreach_out(o, await outreach.read_note(o), kind, service.titles(w), emails)


@router.get("/actions/{kind}/outreach")
async def list_action_outreach(kind: KindPath, user: UserDep, session: SessionDep) -> OutreachResponse:
    """Everyone marked sent or skipped for the action, newest first."""
    return await _history(session, user, kind=kind)


@router.get("/customers/{customer_id}/outreach")
async def list_customer_outreach(customer_id: CustomerPath, user: UserDep, session: SessionDep) -> OutreachResponse:
    """Every note to one customer, across actions."""
    return await _history(session, user, customer_id=customer_id)


@router.delete("/outreach/{outreach_id}", status_code=204)
async def delete_outreach(outreach_id: uuid.UUID, user: UserDep, session: SessionDep) -> Response:
    """Undo: the person goes back into the action's queue."""
    await outreach.delete(session, user, outreach_id)
    return Response(status_code=204)


@router.get("/outreach/contacted")
async def get_contacted(user: UserDep, session: SessionDep) -> ContactedResponse:
    """When each customer was last sent a note, for the "Contacted" chips."""
    return ContactedResponse(contacted={
        cid: ContactedOut(sent_at=int(at.timestamp()), action_kind=kind)
        for cid, (at, kind) in (await outreach.contacted(session, user)).items()
    })


async def _history(session: AsyncSession, user: CurrentUser, **where: str) -> OutreachResponse:
    rows = await outreach.history(session, user, **where)
    if not rows:
        return OutreachResponse(outreach=[])
    titles = service.titles(await _writer(session, user))
    emails = await service.emails_by_id(user)
    notes = await outreach.read_notes(rows)
    return OutreachResponse(outreach=[_outreach_out(o, n, kind, titles, emails) for (o, kind), n in zip(rows, notes)])


def _outreach_out(
    o: Outreach, note: outreach.Note, kind: str, titles: dict[str, str], emails: dict[str, str]
) -> OutreachOut:
    return OutreachOut(
        id=str(o.id), action_kind=kind, action_title=titles.get(kind, "A removed action"), customer_id=o.customer_id,
        email=emails.get(o.customer_id), status=o.status, subject=note.subject, body=note.body,
        sent_at=int(o.sent_at.timestamp()) if o.sent_at else None, created_at=int(o.created_at.timestamp()),
    )
