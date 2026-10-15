"""Stored Stripe objects: importing an account, then keeping it current.

- Import (backfill): every payment intent, invoice, subscription and customer, a page at a time.
  Progress is saved with each page, so an import cut off by a deploy resumes where it stopped.
- Webhooks and the Events API only say *which* object changed. The worker re-reads that object from
  Stripe, with the same expansions as the import, and stores it. So repeated or out-of-order events
  don't matter, and neither does the shape of an event's payload.
- Refresh replays the account's events since its cursor, then waits briefly for those re-reads.
  Stripe keeps events for 30 days; an account whose cursor is older than that is imported again.

Objects are stored per (account, livemode) and shared by every user with a key to the account;
what each user is shown is limited by their own key's permissions (see app/fetch.py).
"""

import asyncio
import logging
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import stripe
from cachetools import TTLCache
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import get_cipher
from app.db import sessionmaker
from app.db_models import StripeAccount, StripeBackfill, StripeCredential, StripeObject, StripeSyncQueue
from app.projection import PROJECTION_REV, project
from app.stripe_client import STRIPE_API_VERSION, Account, own_key_accounts

log = logging.getLogger("stoke.sync")

# Stored objects are tagged with the API version they were read at and the projection they were
# stored with; reads only use an account's active version (see scripts/resync.py).
SYNC_VERSION = f"{STRIPE_API_VERSION}/{PROJECTION_REV}"

OBJECT_TYPES = ("customer", "subscription", "invoice", "payment_intent")
# The key permission each needs, named as in app/credentials.py.
PERMISSION = {
    "payment_intent": "PaymentIntents",
    "invoice": "Invoices",
    "subscription": "Subscriptions",
    "customer": "Customers",
}
# Customers aren't expanded onto payments and subscriptions: they're stored once, as their own
# objects, and joined on read, so a changed email is one update.
EXPAND = {
    # Includes the dispute's balance transactions: exactly what it withdrew, charged and returned.
    "payment_intent": ["latest_charge.balance_transaction", "latest_charge.refunds", "latest_charge.dispute"],
    "invoice": ["payments"],
    # The latest invoice supplies the plan name and a copy of the email that survives customer deletion.
    "subscription": ["latest_invoice"],
    "customer": [],
}

EVENTS_RETENTION = timedelta(days=29)  # Stripe keeps 30 days; a day's margin
CURSOR_OVERLAP = timedelta(seconds=60)  # events are listed from a little before the cursor
REFRESH_WAIT_SECONDS = 20  # how long a refresh waits for the objects its events name
HEARTBEAT_STALE = timedelta(minutes=2)  # an import or re-read this quiet was cut off; take it over
MAX_ATTEMPTS = 5
BACKFILL_CONCURRENCY = 4  # object types imported at once, across all accounts
POLL_SECONDS = 1.0


class Importing(Exception):
    """An account in the request's scope hasn't finished its first import."""

    def __init__(self, account_id: str):
        super().__init__(account_id)
        self.account_id = account_id


def _now() -> datetime:
    return datetime.now(UTC)


def _ts(unix: int | None) -> datetime | None:
    return datetime.fromtimestamp(unix, UTC) if unix is not None else None


def _api_version(version: str) -> str:
    return version.rsplit("/", 1)[0]


def _options(account: Account, version: str) -> dict:
    return {"stripe_version": _api_version(version)}


def _service(client: stripe.StripeClient, obj_type: str):
    return {
        "payment_intent": client.v1.payment_intents,
        "invoice": client.v1.invoices,
        "subscription": client.v1.subscriptions,
        "customer": client.v1.customers,
    }[obj_type]


def _clear_fetch_cache(account_id: str) -> None:
    from app import fetch  # fetch reads through this module

    fetch.clear_account(account_id)


# --- Accounts and their keys ----------------------------------------------------------------------

_data_keys: TTLCache[tuple[str, bool], bytes] = TTLCache(maxsize=1024, ttl=3600)


async def account_row(account_id: str, livemode: bool) -> StripeAccount | None:
    async with sessionmaker()() as session:
        return await session.get(StripeAccount, (account_id, livemode))


async def account_key(row: StripeAccount) -> bytes:
    """The data key that encrypts this account's stored emails."""
    k = (row.account_id, row.livemode)
    if (key := _data_keys.get(k)) is None:
        key = bytes.fromhex(await get_cipher().decrypt(row.sealed_key, row.aad))
        _data_keys[k] = key
    return key


_accounts: TTLCache[tuple[str, bool, str | None], Account] = TTLCache(maxsize=1024, ttl=60)


async def account_for(account_id: str, livemode: bool, need: str | None = None) -> Account | None:
    """A client for an account outside any user's request (the worker): a stored key to it, preferring
    one that can read `need` (a permission name)."""
    cache_key = (account_id, livemode, need)
    if (cached := _accounts.get(cache_key)) is not None:
        return cached

    q = select(StripeCredential).where(StripeCredential.livemode == livemode, StripeCredential.status != "invalid")
    if account_id.startswith("key-"):
        try:
            q = q.where(StripeCredential.id == uuid.UUID(account_id.removeprefix("key-")))
        except ValueError:
            return None
    else:
        q = q.where(StripeCredential.stripe_account_id == account_id)
    async with sessionmaker()() as session:
        creds = list(await session.scalars(q))
    if need:
        creds = [c for c in creds if need not in c.missing_permissions]
    creds.sort(key=lambda c: len(c.missing_permissions))

    account: Account | None = None
    if creds:
        # Empty if the credential's Stripe App was just found uninstalled; the next call tries another.
        account = next(iter(await own_key_accounts(creds[:1])), None)
    if account is not None:
        _accounts[cache_key] = account
    return account


async def purge(account_id: str, livemode: bool) -> None:
    """Delete everything stored for an account."""
    async with sessionmaker()() as session, session.begin():
        for model in (StripeObject, StripeSyncQueue, StripeBackfill, StripeAccount):
            await session.execute(delete(model).where(model.account_id == account_id, model.livemode == livemode))
    _data_keys.pop((account_id, livemode), None)
    _clear_fetch_cache(account_id)


async def forget_if_orphaned(account_id: str, livemode: bool) -> None:
    """After a key is removed: delete the account's stored data unless another key still reads it."""
    if not account_id.startswith("key-"):
        async with sessionmaker()() as session:
            other = await session.scalar(select(StripeCredential.id).where(
                StripeCredential.stripe_account_id == account_id, StripeCredential.livemode == livemode
            ).limit(1))
        if other is not None:
            return
    await purge(account_id, livemode)


# --- Storing --------------------------------------------------------------------------------------


async def _upsert(
    session: AsyncSession, row: StripeAccount, key: bytes, version: str, obj_type: str,
    objs: list[dict], fetched_at: datetime,
) -> None:
    if not objs:
        return
    stmt = insert(StripeObject).values([
        {
            "account_id": row.account_id, "livemode": row.livemode, "version": version, "object": obj_type,
            "id": o["id"], "created": _ts(o.get("created")), "data": project(obj_type, o, key),
            "fetched_at": fetched_at,
        }
        for o in objs
    ])
    await session.execute(stmt.on_conflict_do_update(
        index_elements=["account_id", "livemode", "version", "object", "id"],
        set_={
            # A deleted customer comes back without its creation date.
            "created": func.coalesce(stmt.excluded.created, StripeObject.created),
            "data": stmt.excluded.data,
            "fetched_at": stmt.excluded.fetched_at,
        },
        where=StripeObject.fetched_at < stmt.excluded.fetched_at,
    ))


# --- Import ---------------------------------------------------------------------------------------


async def start_backfill(
    account_id: str, livemode: bool, missing_permissions: Iterable[str] = (), *,
    version: str = SYNC_VERSION, restart: bool = False,
) -> None:
    """Make sure the account is being (or has been) imported. Safe to call repeatedly.

    Creates the account and one import per object type its key can read. Types that were skipped
    for lack of permission, or failed, are queued again once they can be read. `restart` imports
    everything again (an account whose event cursor is too old to catch up from), unless an import
    is already running. A `version` other than the active one is a resync.
    """
    missing = set(missing_permissions)
    now = _now()
    async with sessionmaker()() as session, session.begin():
        if await session.get(StripeAccount, (account_id, livemode)) is None:
            new = StripeAccount(account_id=account_id, livemode=livemode)
            sealed = await get_cipher().encrypt(os.urandom(32).hex(), new.aad)
            await session.execute(insert(StripeAccount).values(
                account_id=account_id, livemode=livemode, active_version=version,
                # Events from before the import started are reflected in what it reads; events after
                # it started are replayed when it finishes.
                events_cursor=now,
                key_ciphertext=sealed.ciphertext, key_wrapped_dek=sealed.wrapped_dek, key_cipher=sealed.cipher,
            ).on_conflict_do_nothing())
        # Serializes concurrent calls for the same account.
        row = await session.get(StripeAccount, (account_id, livemode), with_for_update=True, populate_existing=True)
        assert row is not None
        if version != row.active_version:
            row.target_version = version

        existing = {b.object: b for b in await session.scalars(select(StripeBackfill).where(
            StripeBackfill.account_id == account_id, StripeBackfill.livemode == livemode,
            StripeBackfill.version == version,
        ))}
        if restart and any(b.state in ("pending", "running") for b in existing.values()):
            restart = False
        if restart:
            row.events_cursor = now
        for obj_type in OBJECT_TYPES:
            readable = PERMISSION[obj_type] not in missing
            b = existing.get(obj_type)
            if b is None:
                session.add(StripeBackfill(
                    account_id=account_id, livemode=livemode, version=version, object=obj_type,
                    state="pending" if readable else "skipped", count=0, attempts=0,
                ))
            elif readable and (restart or b.state in ("skipped", "failed")):
                if restart or b.state == "skipped":
                    b.starting_after, b.count = None, 0  # a failed import resumes; others start over
                b.state, b.attempts, b.error, b.retry_at = "pending", 0, None, None
                b.started_at = b.finished_at = b.heartbeat_at = None
    # Nothing to import (the key can read none of it): done already.
    await _maybe_complete(None, account_id, livemode, version)


async def _claim_backfill() -> StripeBackfill | None:
    now = _now()
    async with sessionmaker()() as session, session.begin():
        b = await session.scalar(
            select(StripeBackfill)
            .where(or_(
                and_(StripeBackfill.state == "pending",
                     or_(StripeBackfill.retry_at.is_(None), StripeBackfill.retry_at <= now)),
                and_(StripeBackfill.state == "running", StripeBackfill.heartbeat_at < now - HEARTBEAT_STALE),
            ))
            .order_by(StripeBackfill.retry_at.nulls_first())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if b is None:
            return None
        # started_at is this run's claim: a run whose claim was replaced (taken over, or restarted) stops.
        b.state, b.started_at, b.heartbeat_at = "running", now, now
    return b


def _pk(model, b: StripeBackfill):
    return (model.account_id == b.account_id, model.livemode == b.livemode,
            model.version == b.version, model.object == b.object)


async def _end_run(b: StripeBackfill, claim: datetime, **values) -> bool:
    async with sessionmaker()() as session, session.begin():
        result = await session.execute(
            update(StripeBackfill).where(*_pk(StripeBackfill, b), StripeBackfill.started_at == claim).values(**values)
        )
    return result.rowcount > 0


async def _mark_credential(account: Account, *, invalid: bool = False, missing: str | None = None) -> None:
    if account.credential_id is None:
        return
    async with sessionmaker()() as session, session.begin():
        cred = await session.get(StripeCredential, uuid.UUID(account.credential_id))
        if cred is None:
            return
        if invalid:
            cred.status, cred.missing_permissions = "invalid", []
        elif missing and missing not in cred.missing_permissions:
            cred.status, cred.missing_permissions = "missing_permissions", [*cred.missing_permissions, missing]
    _accounts.clear()
    from app.stripe_client import clear_scope_cache

    clear_scope_cache()


async def run_backfill(b: StripeBackfill) -> None:
    """Import one object type of one account, a page at a time, from where it last stopped."""
    claim = b.started_at
    assert claim is not None
    need = PERMISSION[b.object]
    account = await account_for(b.account_id, b.livemode, need)
    row = await account_row(b.account_id, b.livemode)
    if row is None:
        return  # the account was removed meanwhile
    if account is None:
        await _end_run(b, claim, state="failed", error="No usable Stripe key for this account", finished_at=_now())
        return
    key = await account_key(row)
    params: dict = {"limit": 100, "expand": [f"data.{e}" for e in EXPAND[b.object]]}
    if b.object == "subscription":
        params["status"] = "all"  # Stripe omits canceled subscriptions by default
    starting_after = b.starting_after

    try:
        while True:
            fetched_at = _now()
            page = await _service(account.client, b.object).list_async(
                params | ({"starting_after": starting_after} if starting_after else {}), _options(account, b.version)
            )
            objs = [o.to_dict() for o in page.data]
            async with sessionmaker()() as session, session.begin():
                still_ours = await session.execute(
                    update(StripeBackfill).where(*_pk(StripeBackfill, b), StripeBackfill.started_at == claim).values(
                        starting_after=objs[-1]["id"] if objs else starting_after,
                        count=StripeBackfill.count + len(objs),
                        heartbeat_at=_now(),
                    )
                )
                if still_ours.rowcount == 0:
                    return
                await _upsert(session, row, key, b.version, b.object, objs, fetched_at)
            if objs:
                starting_after = objs[-1]["id"]
            if not page.has_more:
                break
    except stripe.AuthenticationError:
        await _mark_credential(account, invalid=True)
        await _end_run(b, claim, state="failed", error="Stripe no longer accepts this key", finished_at=_now())
    except stripe.PermissionError:
        await _mark_credential(account, missing=need)
        await _end_run(b, claim, state="skipped", error=f"The key can't read {need}", finished_at=_now())
    except Exception as exc:
        attempts = b.attempts + 1
        log.warning("Import of %s for %s failed (attempt %d): %s", b.object, b.account_id, attempts, type(exc).__name__)
        if attempts >= MAX_ATTEMPTS:
            await _end_run(b, claim, state="failed", attempts=attempts, error="Stripe couldn't be read", finished_at=_now())
        else:
            await _end_run(b, claim, state="pending", attempts=attempts, started_at=None,
                           retry_at=_now() + timedelta(seconds=10 * 2**attempts))
        return
    else:
        if not await _end_run(b, claim, state="done", error=None, finished_at=_now()):
            return
    finally:
        _clear_fetch_cache(b.account_id)
    await _maybe_complete(account, b.account_id, b.livemode, b.version)


async def _maybe_complete(account: Account | None, account_id: str, livemode: bool, version: str) -> None:
    """Once every type of an import is done (or skipped), the account is ready, or a resync takes over."""
    replay = False
    async with sessionmaker()() as session, session.begin():
        row = await session.get(StripeAccount, (account_id, livemode), with_for_update=True)
        if row is None:
            return
        unfinished = await session.scalar(select(func.count()).where(
            StripeBackfill.account_id == account_id, StripeBackfill.livemode == livemode,
            StripeBackfill.version == version, StripeBackfill.state.not_in(("done", "skipped")),
        ))
        if unfinished:
            return
        if version == row.active_version:
            if row.backfilled_at is None:
                row.backfilled_at = _now()
            replay = True
        elif version == row.target_version:
            row.active_version, row.target_version = version, None
            for model in (StripeObject, StripeBackfill):
                await session.execute(delete(model).where(
                    model.account_id == account_id, model.livemode == livemode, model.version != version
                ))
    _clear_fetch_cache(account_id)
    if replay and account is not None and "Events" not in account.missing_permissions:
        # Changes made while the import ran.
        try:
            await _replay_events(account)
        except Exception as exc:
            log.warning("Replaying events for %s failed: %s", account_id, type(exc).__name__)


# --- Re-reading changed objects -------------------------------------------------------------------


def targets(obj: dict) -> list[tuple[str, str]]:
    """The stored objects a changed Stripe object affects. Reads only ids, which every API version has."""

    def ref(v) -> str | None:
        return v.get("id") if isinstance(v, dict) else v if isinstance(v, str) else None

    match obj.get("object"):
        case "payment_intent":
            pairs = [("payment_intent", obj.get("id"))]
        case "charge" | "refund" | "dispute":
            pairs = [("payment_intent", ref(obj.get("payment_intent")))]
        case "invoice":
            parent = ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription")
            # The subscription stores its latest invoice.
            pairs = [("invoice", obj.get("id")), ("subscription", ref(obj.get("subscription")) or ref(parent))]
        case "invoice_payment":
            pairs = [("invoice", ref(obj.get("invoice")))]
        case "subscription":
            pairs = [("subscription", obj.get("id"))]
        case "customer":
            pairs = [("customer", obj.get("id"))]
        case _:
            pairs = []
    return [(t, i) for t, i in pairs if isinstance(i, str) and i]


async def enqueue(
    account_id: str, livemode: bool, found: Iterable[tuple[str, str]], session: AsyncSession | None = None
) -> None:
    found = set(found)
    if not found:
        return
    now = _now()
    stmt = insert(StripeSyncQueue).values([
        {"account_id": account_id, "livemode": livemode, "object": t, "id": i, "enqueued_at": now, "attempts": 0}
        for t, i in found
    ])
    # A notice for an object already being re-read resets it, so it's read again after this one.
    stmt = stmt.on_conflict_do_update(
        index_elements=["account_id", "livemode", "object", "id"],
        set_={"enqueued_at": stmt.excluded.enqueued_at, "claimed_at": None},
    )
    if session is not None:
        await session.execute(stmt)
        return
    async with sessionmaker()() as s, s.begin():
        await s.execute(stmt)


async def _claim_jobs(account: Account | None, limit: int = 10) -> list[StripeSyncQueue]:
    now = _now()
    async with sessionmaker()() as session, session.begin():
        q = select(StripeSyncQueue).where(
            or_(StripeSyncQueue.claimed_at.is_(None), StripeSyncQueue.claimed_at < now - HEARTBEAT_STALE)
        )
        if account is not None:
            q = q.where(StripeSyncQueue.account_id == account.id, StripeSyncQueue.livemode == account.livemode)
        jobs = list(await session.scalars(q.order_by(StripeSyncQueue.enqueued_at).limit(limit).with_for_update(skip_locked=True)))
        for job in jobs:
            job.claimed_at = now
    return jobs


def _job_pk(job: StripeSyncQueue):
    return (StripeSyncQueue.account_id == job.account_id, StripeSyncQueue.livemode == job.livemode,
            StripeSyncQueue.object == job.object, StripeSyncQueue.id == job.id,
            # Unchanged since claimed: a newer notice keeps the job for another read.
            StripeSyncQueue.enqueued_at == job.enqueued_at)


async def fetch_object(account: Account, obj_type: str, obj_id: str, version: str = SYNC_VERSION) -> dict | None:
    """The object as Stripe has it now, expanded as stored. None if it no longer exists."""
    try:
        obj = await _service(account.client, obj_type).retrieve_async(
            obj_id, {"expand": EXPAND[obj_type]} if EXPAND[obj_type] else None, _options(account, version)
        )
    except stripe.InvalidRequestError as exc:
        if exc.code == "resource_missing":
            return None
        raise
    return obj.to_dict()


async def _process(job: StripeSyncQueue, given: Account | None) -> None:
    row = await account_row(job.account_id, job.livemode)
    account = given if given is not None and given.id == job.account_id else (
        await account_for(job.account_id, job.livemode, PERMISSION[job.object]) if row is not None else None
    )
    try:
        if row is None or account is None or PERMISSION[job.object] in account.missing_permissions:
            pass  # nothing to update it with
        else:
            key = await account_key(row)
            for version in filter(None, (row.active_version, row.target_version)):
                fetched_at = _now()
                obj = await fetch_object(account, job.object, job.id, version)
                async with sessionmaker()() as session, session.begin():
                    if obj is None:
                        await session.execute(delete(StripeObject).where(
                            StripeObject.account_id == job.account_id, StripeObject.livemode == job.livemode,
                            StripeObject.version == version, StripeObject.object == job.object,
                            StripeObject.id == job.id,
                        ))
                    else:
                        await _upsert(session, row, key, version, job.object, [obj], fetched_at)
    except Exception as exc:
        log.warning("Re-reading %s %s for %s failed: %s", job.object, job.id, job.account_id, type(exc).__name__)
        async with sessionmaker()() as session, session.begin():
            if job.attempts + 1 >= MAX_ATTEMPTS:
                await session.execute(delete(StripeSyncQueue).where(*_job_pk(job)))
            else:
                await session.execute(update(StripeSyncQueue).where(*_job_pk(job)).values(
                    attempts=job.attempts + 1, claimed_at=None
                ))
        return
    async with sessionmaker()() as session, session.begin():
        await session.execute(delete(StripeSyncQueue).where(*_job_pk(job)))
    _clear_fetch_cache(job.account_id)


async def drain(account: Account | None = None, *, seconds: float | None = None) -> int:
    """Re-read queued objects (only `account`'s, if given) until the queue is empty or time runs out."""
    loop = asyncio.get_running_loop()
    deadline = None if seconds is None else loop.time() + seconds
    done = 0
    while jobs := await _claim_jobs(account):
        await asyncio.gather(*(_process(job, account) for job in jobs))
        done += len(jobs)
        if deadline is not None and loop.time() > deadline:
            break
    return done


# --- Events ---------------------------------------------------------------------------------------


async def _replay_events(account: Account, wait: float | None = None) -> None:
    """Queue every object named by the account's events since its cursor, then move the cursor on."""
    row = await account_row(account.id, account.livemode)
    if row is None:
        return
    started = _now()
    since = int((row.events_cursor - CURSOR_OVERLAP).timestamp())
    page = await account.client.v1.events.list_async({"limit": 100, "created": {"gt": since}})
    found: set[tuple[str, str]] = set()
    async for event in page.auto_paging_iter():
        found.update(targets((event.to_dict().get("data") or {}).get("object") or {}))
    async with sessionmaker()() as session, session.begin():
        await enqueue(account.id, account.livemode, found, session)
        await session.execute(update(StripeAccount).where(
            StripeAccount.account_id == account.id, StripeAccount.livemode == account.livemode,
            StripeAccount.events_cursor < started,
        ).values(events_cursor=started))
    if wait is not None:
        await drain(account, seconds=wait)


async def ensure_ready(account: Account) -> StripeAccount:
    """The account's stored state, or Importing (starting the import if it never started)."""
    row = await account_row(account.id, account.livemode)
    if row is None:
        await start_backfill(account.id, account.livemode, account.missing_permissions)
        row = await account_row(account.id, account.livemode)
    if row is None or row.backfilled_at is None:
        raise Importing(account.id)
    return row


_catching_up: dict[tuple[str, bool], asyncio.Future] = {}


async def catch_up(account: Account) -> None:
    """Bring the account's stored objects up to date with Stripe (the dashboard's Refresh). A view
    reads payments and subscriptions at once; both share one catch-up."""
    k = (account.id, account.livemode)
    if (running := _catching_up.get(k)) is None:
        running = _catching_up[k] = asyncio.ensure_future(_catch_up(account))
        running.add_done_callback(lambda _: _catching_up.pop(k, None))
    await asyncio.shield(running)


async def _catch_up(account: Account) -> None:
    row = await ensure_ready(account)
    if "Events" in account.missing_permissions or row.events_cursor < _now() - EVENTS_RETENTION:
        # Too long ago to catch up from events: import again. What's stored is shown meanwhile.
        await start_backfill(account.id, account.livemode, account.missing_permissions, restart=True)
        return
    try:
        await _replay_events(account, wait=REFRESH_WAIT_SECONDS)
    except stripe.PermissionError:
        # A key checked before "Events: Read" was asked for: note it, and import again instead.
        await _mark_credential(account, missing="Events")
        await start_backfill(account.id, account.livemode, account.missing_permissions, restart=True)
    _clear_fetch_cache(account.id)


async def handle_event(event: dict) -> None:
    """A verified webhook event: queue the objects it names for a re-read."""
    account_id, livemode = event.get("account"), bool(event.get("livemode"))
    if not account_id:
        return  # Connect endpoints carry the account; anything else isn't for us
    found = targets((event.get("data") or {}).get("object") or {})
    async with sessionmaker()() as session, session.begin():
        row = await session.get(StripeAccount, (account_id, livemode))
        if row is None:
            return  # an account Stoke doesn't store
        await enqueue(account_id, livemode, found, session)
        # Webhooks are assumed to arrive (Stripe retries for days), so a refresh only needs to replay
        # events since the latest one delivered.
        if (created := _ts(event.get("created"))) and created > row.events_cursor:
            row.events_cursor = created


# --- Worker ---------------------------------------------------------------------------------------


async def run_worker() -> None:
    """Runs imports and re-reads in the background, for as long as the app runs."""
    loop = asyncio.get_running_loop()
    imports: set[asyncio.Task] = set()
    try:
        while True:
            worked = 0
            try:
                while len(imports) < BACKFILL_CONCURRENCY and (b := await _claim_backfill()) is not None:
                    task = loop.create_task(run_backfill(b))
                    imports.add(task)
                    task.add_done_callback(imports.discard)
                    worked += 1
                worked += await drain(seconds=10)
            except Exception:
                log.exception("Sync worker error")
            if not worked:
                await asyncio.sleep(POLL_SECONDS)
    finally:
        for task in imports:
            task.cancel()


# --- Status ---------------------------------------------------------------------------------------

SyncState = Literal["not_started", "importing", "ready", "failed"]


@dataclass(frozen=True)
class TypeProgress:
    object: str
    state: str
    count: int


@dataclass(frozen=True)
class AccountProgress:
    state: SyncState
    objects: list[TypeProgress]


async def progress(keys: Iterable[tuple[str, bool]]) -> dict[tuple[str, bool], AccountProgress]:
    """Import state of each (account id, livemode)."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    ids = [k[0] for k in keys]
    async with sessionmaker()() as session:
        rows = {(r.account_id, r.livemode): r for r in await session.scalars(
            select(StripeAccount).where(StripeAccount.account_id.in_(ids))
        )}
        backfills = list(await session.scalars(select(StripeBackfill).where(StripeBackfill.account_id.in_(ids))))
    out: dict[tuple[str, bool], AccountProgress] = {}
    for k in keys:
        row = rows.get(k)
        if row is None:
            out[k] = AccountProgress("not_started", [])
            continue
        mine = sorted(
            (b for b in backfills if (b.account_id, b.livemode) == k and b.version == row.active_version),
            key=lambda b: OBJECT_TYPES.index(b.object),
        )
        states = {b.state for b in mine}
        state: SyncState = (
            "failed" if "failed" in states
            else "importing" if states & {"pending", "running"} or row.backfilled_at is None
            else "ready"
        )
        out[k] = AccountProgress(state, [TypeProgress(b.object, b.state, b.count) for b in mine])
    return out
