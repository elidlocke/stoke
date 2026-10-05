"""Live Stripe reads, returning normalized Payments."""

import asyncio
from dataclasses import dataclass

from cachetools import TTLCache

from app.aggregate import Payment, invoices_by_payment_intent, normalize_payment
from app.config import get_settings
from app.stripe_client import Account

PI_EXPAND = ["data.customer", "data.latest_charge.balance_transaction", "data.latest_charge.refunds"]
INVOICE_EXPAND = ["data.payments"]

# A payment can be attempted well after its invoice was created (dunning retries), so invoices
# are fetched from a little before the window to still find the invoice for every payment.
INVOICE_LOOKBACK = 45 * 86400


@dataclass(frozen=True)
class _CachedWindow:
    since: int | None  # None = all time
    payments: list[Payment]


_window_cache: TTLCache[str, _CachedWindow] | None = None


def _cache() -> TTLCache[str, _CachedWindow]:
    global _window_cache
    if _window_cache is None:
        _window_cache = TTLCache(maxsize=1024, ttl=get_settings().cache_ttl_seconds)
    return _window_cache


def clear_cache() -> None:
    _cache().clear()


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
    cached = cache.get(account.id)
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
    cache[account.id] = _CachedWindow(since=since, payments=payments)
    return payments
