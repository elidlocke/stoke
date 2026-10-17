"""The writer's free subscribers, from the CSV Substack exports (Subscribers → ⋯ → Export).

Only free subscribers are kept (paid ones are in Stripe), and only what the Free -> paid action needs:
email and first name, encrypted under a data key of the writer's own, plus start date and engagement
counts for ranking (actions.upgrade_score). The file itself is never stored. Each publication the writer
runs has its own list, and each upload replaces that publication's last, so a list is as fresh as its latest
export. The Free -> paid action ranks them all together.
"""

import csv
import io
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from cachetools import TTLCache
from sqlalchemy import delete as sql_delete
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions import FreeSubscriber, first_name
from app.auth import CurrentUser
from app.crypto import aead_open, aead_seal, get_cipher
from app.customer_id import customer_id
from app.db_models import SubstackList, SubstackSubscriber, substack_subscriber_aad
from app.substack import SubstackError

MAX_ROWS = 200_000
REQUIRED = ("Email", "Name", "Type", "Activity", "Start date")
# Engagement columns, by the field each fills. A missing column reads as 0.
_COUNTS = {
    "emails_received_6mo": "Emails received (6mo)",
    "emails_opened_6mo": "Emails opened (6mo)",
    "days_active_30d": "Days active (30d)",
    "post_views_30d": "Post views (30d)",
    "links_clicked": "Links clicked",
    "comments": "Comments",
    "shares": "Shares",
}
# subscriber-export-2026-10-15-15-20-00.csv
_EXPORTED = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

NOT_AN_EXPORT = (
    "That doesn't look like a Substack subscriber export. In Substack, go to Subscribers, click ⋯ and choose Export, "
    "then upload that file."
)

_data_keys: TTLCache[tuple[uuid.UUID, str], bytes] = TTLCache(maxsize=1024, ttl=3600)


class SubstackListError(SubstackError):
    """The upload can't be read; the message is safe to show and never echoes the file."""


@dataclass(frozen=True)
class Export:
    exported_at: datetime
    free: list[FreeSubscriber]


@dataclass(frozen=True)
class FreeList:
    exported_at: datetime  # the oldest of the writer's exports
    subscribers: list[FreeSubscriber]  # from every publication, each reader once


def exported_at(filename: str, now: datetime) -> datetime:
    """When the export was made, from its filename (read as UTC); `now` when the name doesn't say."""
    if m := _EXPORTED.search(filename):
        try:
            return datetime(*(int(g) for g in m.groups()), tzinfo=UTC)
        except ValueError:
            pass
    return now


def _int(value: str | None) -> int:
    try:
        return max(int(float((value or "").strip() or 0)), 0)
    except ValueError:
        return 0


def _started(value: str | None) -> int | None:
    try:
        return int(datetime.fromisoformat((value or "").strip().replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def parse(filename: str, text: str, now: datetime | None = None) -> Export:
    """The free subscribers in an export. Raises SubstackListError when it isn't one."""
    now = now or datetime.now(UTC)
    reader = csv.DictReader(io.StringIO(text.removeprefix("﻿")))
    if not reader.fieldnames or any(col not in reader.fieldnames for col in REQUIRED):
        raise SubstackListError(NOT_AN_EXPORT)
    seen: dict[str, FreeSubscriber] = {}
    try:
        for i, row in enumerate(reader):
            if i >= MAX_ROWS:
                raise SubstackListError(f"That export has more than {MAX_ROWS:,} subscribers, more than Stoke can take.")
            if (row.get("Type") or "").strip().lower() != "free":
                continue
            email = (row.get("Email") or "").strip().lower()
            started = _started(row.get("Start date"))
            if not _EMAIL.match(email) or started is None:
                continue
            seen.setdefault(email, FreeSubscriber(
                email=email, first_name=first_name(row.get("Name")), started=started,
                activity=min(_int(row.get("Activity")), 5), **{f: _int(row.get(col)) for f, col in _COUNTS.items()},
            ))
    except csv.Error:
        raise SubstackListError(NOT_AN_EXPORT) from None
    return Export(exported_at=exported_at(filename, now), free=list(seen.values()))


async def _key(row: SubstackList) -> bytes:
    cache_key = (row.user_id, row.publication)
    if (key := _data_keys.get(cache_key)) is None:
        key = bytes.fromhex(await get_cipher().decrypt(row.sealed_key, row.aad))
        _data_keys[cache_key] = key
    return key


def _of(user: CurrentUser, publication: str):
    return (SubstackSubscriber.user_id == user.id) & (SubstackSubscriber.publication == publication)


async def save(session: AsyncSession, user: CurrentUser, publication: str, export: Export) -> SubstackList:
    """Replaces the publication's list with this export's."""
    row = await session.get(SubstackList, (user.id, publication))
    if row is None:
        row = SubstackList(user_id=user.id, publication=publication)
        sealed = await get_cipher().encrypt(os.urandom(32).hex(), row.aad)
        row.key_ciphertext, row.key_wrapped_dek, row.key_cipher = sealed.ciphertext, sealed.wrapped_dek, sealed.cipher
        session.add(row)
    row.exported_at, row.uploaded_at, row.free_count = export.exported_at, datetime.now(UTC), len(export.free)
    await session.flush()
    key = await _key(row)
    await session.execute(sql_delete(SubstackSubscriber).where(_of(user, publication)))
    rows = []
    for s in export.free:
        cid = customer_id(s.email)
        aad = substack_subscriber_aad(user.id, publication, cid)
        rows.append({
            "user_id": user.id, "publication": publication, "customer_id": cid,
            "email": aead_seal(key, s.email.encode(), aad),
            "first_name": aead_seal(key, s.first_name.encode(), aad) if s.first_name else None,
            "started_at": datetime.fromtimestamp(s.started, UTC), "activity": s.activity,
            **{f: getattr(s, f) for f in _COUNTS},
        })
    for i in range(0, len(rows), 5000):
        await session.execute(insert(SubstackSubscriber), rows[i:i + 5000])
    await session.commit()
    return row


async def metas(session: AsyncSession, user: CurrentUser) -> list[SubstackList]:
    """The writer's lists, one per publication uploaded."""
    return list(await session.scalars(
        select(SubstackList).where(SubstackList.user_id == user.id).order_by(SubstackList.publication)
    ))


def _more_engaged(a: FreeSubscriber, b: FreeSubscriber) -> FreeSubscriber:
    """A reader free on two publications is ranked by the one they're more engaged with."""
    return a if (a.activity, -a.started) >= (b.activity, -b.started) else b


async def load(session: AsyncSession, user: CurrentUser) -> FreeList | None:
    """The free subscribers of all the writer's publications, decrypted, each reader once; None until they
    upload an export."""
    lists = await metas(session, user)
    if not lists:
        return None
    keys = {row.publication: await _key(row) for row in lists}
    subs = (await session.scalars(select(SubstackSubscriber).where(SubstackSubscriber.user_id == user.id))).all()
    by_email: dict[str, FreeSubscriber] = {}
    for s in subs:
        key, aad = keys[s.publication], substack_subscriber_aad(user.id, s.publication, s.customer_id)
        sub = FreeSubscriber(
            email=aead_open(key, s.email, aad).decode(),
            first_name=aead_open(key, s.first_name, aad).decode() if s.first_name else None,
            started=int(s.started_at.timestamp()), activity=s.activity, **{f: getattr(s, f) for f in _COUNTS},
        )
        seen = by_email.get(sub.email)
        by_email[sub.email] = _more_engaged(seen, sub) if seen else sub
    return FreeList(min(row.exported_at for row in lists), list(by_email.values()))


async def delete(session: AsyncSession, user: CurrentUser, publication: str) -> None:
    """Forgets the publication's free subscribers."""
    await session.execute(
        sql_delete(SubstackList).where((SubstackList.user_id == user.id) & (SubstackList.publication == publication))
    )
    await session.commit()
    _data_keys.pop((user.id, publication), None)


def forget_user(user_id: uuid.UUID) -> None:
    """Drops a deleted user's cached data keys."""
    for key in [k for k in _data_keys if k[0] == user_id]:
        del _data_keys[key]


def clear_cache() -> None:
    _data_keys.clear()
