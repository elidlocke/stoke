"""Live Stripe reads, returning normalized Payments and Subscriptions."""

import asyncio
from dataclasses import dataclass

import stripe
from cachetools import TTLCache

from app.aggregate import Payment, Subscription, invoices_by_payment_intent, normalize_payment, normalize_subscription
from app.config import get_settings
from app.stripe_client import Account, MissingPermission

PI_EXPAND = [
    "data.customer",
    "data.latest_charge.balance_transaction",
    "data.latest_charge.refunds",
    # Includes the dispute's balance transactions: exactly what it withdrew, charged and returned.
    "data.latest_charge.dispute",
]
INVOICE_EXPAND = ["data.payments"]
# The latest invoice supplies the plan name and a copy of the email that survives customer deletion.
SUBSCRIPTION_EXPAND = ["data.customer", "data.latest_invoice"]

# A payment can be attempted well after its invoice was created (dunning retries), so invoices
# are fetched from a little before the window to still find the invoice for every payment.
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


def clear_credential(credential_id: object) -> None:
    """Drop what was read with one stored key, after it's replaced or removed."""
    suffix = f":{credential_id}"
    for cache in (_cache(), _subscriptions_cache()):
        for key in [k for k in cache if k.endswith(suffix)]:
            cache.pop(key, None)


def _covers(cached_since: int | None, since: int | None) -> bool:
    return cached_since is None or (since is not None and cached_since <= since)


async def _collect(page) -> list[dict]:
    return [obj.to_dict() async for obj in page.auto_paging_iter()]


def _params(expand: list[str], since: int | None) -> dict:
    params: dict = {"limit": 100, "expand": expand}
    if since is not None:
        params["created"] = {"gte": since}
    return params


async def payments_since(account: Account, since: int | None, refresh: bool = False) -> list[Payment]:
    """All payments (PaymentIntents, joined to their invoices) on `account` created at or after `since`.

    One window per account is cached; a narrower period is served by filtering a wider
    cached window rather than calling Stripe again.
    """
    cache = _cache()
    cached = cache.get(account.cache_key)
    if cached and not refresh and _covers(cached.since, since):
        return [p for p in cached.payments if since is None or p.created >= since]

    client, opts = account.client, account.options
    invoice_since = None if since is None else since - INVOICE_LOOKBACK
    pi_page, invoice_page = await asyncio.gather(
        client.v1.payment_intents.list_async(_params(PI_EXPAND, since), opts),
        client.v1.invoices.list_async(_params(INVOICE_EXPAND, invoice_since), opts),
    )
    intents, invoices = await asyncio.gather(_collect(pi_page), _collect(invoice_page))

    by_pi = invoices_by_payment_intent(invoices)
    payments = [
        p for pi in intents if (p := normalize_payment(pi, by_pi.get(pi["id"]), account.id)) is not None
    ]
    cache[account.cache_key] = _CachedWindow(since=since, payments=payments)
    return payments


async def subscriptions(account: Account, refresh: bool = False) -> list[Subscription]:
    """Every subscription on `account`, in any status, including canceled ones."""
    cache = _subscriptions_cache()
    if not refresh and (cached := cache.get(account.cache_key)) is not None:
        return cached

    params = {"limit": 100, "status": "all", "expand": SUBSCRIPTION_EXPAND}
    try:
        page = await account.client.v1.subscriptions.list_async(params, account.options)
        raw = await _collect(page)
    except stripe.PermissionError as exc:
        raise MissingPermission("Subscriptions") from exc

    subs = [normalize_subscription(s, account.id) for s in raw]
    cache[account.cache_key] = subs
    return subs
