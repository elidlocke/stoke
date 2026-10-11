"""Normalized Payments and Subscriptions, read from the stored Stripe objects (see app/sync.py)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from cachetools import TTLCache
from sqlalchemy import Text, any_, bindparam, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app import sync
from app.aggregate import Payment, Subscription, invoices_by_payment_intent, normalize_payment, normalize_subscription
from app.config import get_settings
from app.db import sessionmaker
from app.db_models import StripeAccount, StripeObject
from app.projection import unseal
from app.stripe_client import Account, MissingPermission

# A payment can be attempted well after its invoice was created (dunning retries), so invoices
# are read from a little before the window to still find the invoice for every payment.
INVOICE_LOOKBACK = 45 * 86400


@dataclass(frozen=True)
class _CachedWindow:
    since: int | None  # None = all time
    payments: list[Payment]


_window_cache: TTLCache[str, _CachedWindow] | None = None
_subscription_cache: TTLCache[str, list[Subscription]] | None = None


def _cache() -> TTLCache[str, _CachedWindow]:
    global _window_cache
    if _window_cache is None:
        _window_cache = TTLCache(maxsize=1024, ttl=get_settings().cache_ttl_seconds)
    return _window_cache


def _subscriptions_cache() -> TTLCache[str, list[Subscription]]:
    global _subscription_cache
    if _subscription_cache is None:
        _subscription_cache = TTLCache(maxsize=1024, ttl=get_settings().cache_ttl_seconds)
    return _subscription_cache


def clear_cache() -> None:
    _cache().clear()
    _subscriptions_cache().clear()


def _clear_where(match) -> None:
    for cache in (_cache(), _subscriptions_cache()):
        for key in [k for k in cache if match(k)]:
            cache.pop(key, None)


def clear_credential(credential_id: object) -> None:
    """Drop what was read with one stored key, after it's replaced or removed."""
    suffix = f":{credential_id}"
    _clear_where(lambda k: k.endswith(suffix))


def clear_account(account_id: str) -> None:
    """Drop everything read from an account, after its stored objects change."""
    _clear_where(lambda k: k == account_id or k.startswith(f"{account_id}:"))


def _covers(cached_since: int | None, since: int | None) -> bool:
    return cached_since is None or (since is not None and cached_since <= since)


def _require(account: Account, permission: str) -> None:
    if permission in account.missing_permissions:
        raise MissingPermission(permission)


def _can(account: Account, permission: str) -> bool:
    return permission not in account.missing_permissions


async def _load(
    session: AsyncSession, row: StripeAccount, key: bytes, obj_type: str,
    *, since: int | None = None, ids: list[str] | None = None,
) -> list[dict]:
    """Stored objects of one type, newest first (as Stripe lists them), with their emails decrypted."""
    q = select(StripeObject.data).where(
        StripeObject.account_id == row.account_id, StripeObject.livemode == row.livemode,
        StripeObject.version == row.active_version, StripeObject.object == obj_type,
    )
    if since is not None:
        q = q.where(StripeObject.created >= datetime.fromtimestamp(since, UTC))
    if ids is not None:
        q = q.where(StripeObject.id == any_(bindparam("ids", ids, type_=ARRAY(Text))))
    rows = await session.scalars(q.order_by(StripeObject.created.desc(), StripeObject.id.desc()))
    return [unseal(data, key) for data in rows]


async def _with_customers(
    session: AsyncSession, account: Account, row: StripeAccount, key: bytes, objs: list[dict]
) -> None:
    """Put each object's stored customer in place of its customer id, as an expanded read would."""
    if not _can(account, "Customers"):
        return
    ids = sorted({c for o in objs if isinstance(c := o.get("customer"), str)})
    if not ids:
        return
    customers = {c["id"]: c for c in await _load(session, row, key, "customer", ids=ids)}
    for o in objs:
        if (c := customers.get(o.get("customer"))) is not None:
            o["customer"] = c


async def payments_since(account: Account, since: int | None, refresh: bool = False) -> list[Payment]:
    """All payments (PaymentIntents, joined to their invoices) on `account` created at or after `since`.

    One window per account is cached; a narrower period is served by filtering a wider cached
    window. `refresh` first catches the stored objects up with Stripe.
    """
    _require(account, "PaymentIntents")
    if refresh:
        await sync.catch_up(account)
    cache = _cache()
    cached = cache.get(account.cache_key)
    if cached and not refresh and _covers(cached.since, since):
        return [p for p in cached.payments if since is None or p.created >= since]

    row = await sync.ensure_ready(account)
    key = await sync.account_key(row)
    invoice_since = None if since is None else since - INVOICE_LOOKBACK
    async with sessionmaker()() as session:
        intents = await _load(session, row, key, "payment_intent", since=since)
        invoices = await _load(session, row, key, "invoice", since=invoice_since) if _can(account, "Invoices") else []
        await _with_customers(session, account, row, key, intents)

    by_pi = invoices_by_payment_intent(invoices)
    payments = [
        p for pi in intents if (p := normalize_payment(pi, by_pi.get(pi["id"]), account.id)) is not None
    ]
    cache[account.cache_key] = _CachedWindow(since=since, payments=payments)
    return payments


async def subscriptions(account: Account, refresh: bool = False) -> list[Subscription]:
    """Every subscription on `account`, in any status, including canceled ones."""
    _require(account, "Subscriptions")
    if refresh:
        await sync.catch_up(account)
    cache = _subscriptions_cache()
    if not refresh and (cached := cache.get(account.cache_key)) is not None:
        return cached

    row = await sync.ensure_ready(account)
    key = await sync.account_key(row)
    async with sessionmaker()() as session:
        raw = await _load(session, row, key, "subscription")
        await _with_customers(session, account, row, key, raw)

    subs = [normalize_subscription(s, account.id) for s in raw]
    cache[account.cache_key] = subs
    return subs
