"""The writer's actions (on/off and note templates) and the notes sent for them, scoped to their owner.

No email address is stored: a note's recipient is their opaque customer id, and the email is looked
up again from the Stripe data whenever it's needed. The note's text is stored encrypted.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import templates
from app.auth import CurrentUser
from app.crypto import get_cipher
from app.db_models import Outreach, WriterAction


class OutreachError(Exception):
    """The change can't be made; the message is safe to show the user."""


class OutreachNotFound(Exception):
    pass


@dataclass(frozen=True)
class Note:
    subject: str
    body: str


async def read_note(o: Outreach) -> Note:
    data = json.loads(await get_cipher().decrypt(o.sealed_note, o.aad))
    return Note(subject=data["subject"], body=data["body"])


async def read_notes(rows: list[tuple[Outreach, str]]) -> list[Note]:
    return list(await asyncio.gather(*(read_note(o) for o, _ in rows)))


@dataclass(frozen=True)
class Template:
    subject: str
    body: str
    is_default: bool  # not edited by the writer yet
    approved_at: datetime | None


async def settings(session: AsyncSession, user: CurrentUser) -> dict[str, WriterAction]:
    """The writer's action settings by kind. Actions never changed have none: off, with the default template."""
    rows = await session.scalars(select(WriterAction).where(WriterAction.user_id == user.id))
    return {a.kind: a for a in rows}


async def setting(session: AsyncSession, user: CurrentUser, kind: str) -> WriterAction | None:
    return await session.scalar(select(WriterAction).where(WriterAction.user_id == user.id, WriterAction.kind == kind))


def template(kind: str, row: WriterAction | None) -> Template:
    subject, body = templates.default(kind)
    if row is None or (row.subject is None and row.body is None):
        return Template(subject, body, True, row.approved_at if row else None)
    return Template(row.subject if row.subject is not None else subject, row.body if row.body is not None else body,
                    False, row.approved_at)


async def update(
    session: AsyncSession, user: CurrentUser, kind: str, *,
    enabled: bool | None = None, subject: str | None = None, body: str | None = None, approved: bool | None = None,
) -> WriterAction:
    """Changes an action's settings. Editing the template withdraws its approval, unless it's approved in
    the same change."""
    for text in (subject, body):
        if text is not None and (unknown := templates.unknown_fields(text, kind)):
            raise OutreachError(f"Unknown merge field: {', '.join('{{' + f + '}}' for f in unknown)}")
    row = await setting(session, user, kind)
    if row is None:
        row = WriterAction(user_id=user.id, kind=kind, enabled=False)
        session.add(row)
    current = template(kind, row)
    edited = (subject is not None and subject != current.subject) or (body is not None and body != current.body)
    if subject is not None:
        row.subject = subject
    if body is not None:
        row.body = body
    if edited:
        row.approved_at = None
    if approved is not None:
        row.approved_at = datetime.now(UTC) if approved else None
    if enabled is not None:
        row.enabled = enabled
    await session.commit()
    return row


async def history(
    session: AsyncSession, user: CurrentUser, *, kind: str | None = None, customer_id: str | None = None
) -> list[tuple[Outreach, str]]:
    """Notes recorded for the writer, newest first, with their action's kind."""
    q = (
        select(Outreach, WriterAction.kind)
        .join(WriterAction, Outreach.action_id == WriterAction.id)
        .where(Outreach.user_id == user.id)
        .order_by(Outreach.created_at.desc())
    )
    if kind is not None:
        q = q.where(WriterAction.kind == kind)
    if customer_id is not None:
        q = q.where(Outreach.customer_id == customer_id)
    return [(o, k) for o, k in (await session.execute(q)).all()]


async def record(
    session: AsyncSession, user: CurrentUser, action: WriterAction, customer_id: str, status: str, subject: str, body: str
) -> Outreach:
    """A note the writer sent themselves (status sent), or a person they chose to leave out (skipped)."""
    o = Outreach(
        id=uuid.uuid4(), user_id=user.id, action_id=action.id, customer_id=customer_id, status=status,
        sent_at=datetime.now(UTC) if status == "sent" else None,
    )
    sealed = await get_cipher().encrypt(json.dumps({"subject": subject, "body": body}), o.aad)
    o.note_ciphertext, o.note_wrapped_dek, o.note_cipher = sealed.ciphertext, sealed.wrapped_dek, sealed.cipher
    session.add(o)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise OutreachError("They're already marked for this action.")
    return o


async def delete(session: AsyncSession, user: CurrentUser, outreach_id: uuid.UUID) -> None:
    o = await session.scalar(select(Outreach).where(Outreach.id == outreach_id, Outreach.user_id == user.id))
    if o is None:
        raise OutreachNotFound(outreach_id)
    await session.delete(o)
    await session.commit()


@dataclass(frozen=True)
class Tally:
    """The writer's recorded notes, by action kind."""
    sent: dict[str, int]  # notes marked sent
    last_sent: dict[str, datetime]  # when the latest was sent
    marked: dict[str, set[str]]  # customer ids marked sent or skipped: no longer in the queue


async def tally(session: AsyncSession, user: CurrentUser) -> Tally:
    rows = await session.execute(
        select(WriterAction.kind, Outreach.customer_id, Outreach.status, Outreach.sent_at)
        .join(WriterAction, Outreach.action_id == WriterAction.id)
        .where(Outreach.user_id == user.id)
    )
    sent: dict[str, int] = {}
    last_sent: dict[str, datetime] = {}
    marked: dict[str, set[str]] = {}
    for kind, cid, status, sent_at in rows.all():
        marked.setdefault(kind, set()).add(cid)
        if status == "sent":
            sent[kind] = sent.get(kind, 0) + 1
            if sent_at is not None and (kind not in last_sent or sent_at > last_sent[kind]):
                last_sent[kind] = sent_at
    return Tally(sent=sent, last_sent=last_sent, marked=marked)


async def contacted(session: AsyncSession, user: CurrentUser) -> dict[str, tuple[datetime, str]]:
    """Everyone the writer has sent a note to: customer id -> (when the latest was sent, for which action)."""
    rows = await session.execute(
        select(Outreach.customer_id, Outreach.sent_at, WriterAction.kind)
        .join(WriterAction, Outreach.action_id == WriterAction.id)
        .where(Outreach.user_id == user.id, Outreach.status == "sent")
        .order_by(Outreach.sent_at)
    )
    return {cid: (at, kind) for cid, at, kind in rows.all()}
