import asyncio
from dataclasses import asdict
from datetime import UTC, datetime

from app import aggregate, fetch, fx
from app.aggregate import Payment, Subscription
from app.models import (
    AccountOut,
    AccountsResponse,
    AnniversariesResponse,
    AnniversaryEntry,
    CancellationEntry,
    CancellationsResponse,
    CustomerProfileResponse,
    CustomerSummary,
    LeaderboardEntry,
    LeaderboardResponse,
    NewSubscriberEntry,
    NewSubscribersResponse,
    Period,
    TimelineEventOut,
    Window,
)
from app.customer_id import customer_id, resolve
from app.stripe_client import Account, AccountScope, MissingPermission, get_scope


class UnknownAccount(Exception):
    pass


class UnknownCustomer(Exception):
    pass


async def _to_reporting(payments: list[Payment], reporting_currency: str) -> list[Payment]:
    rates = await fx.get_rates(aggregate.needed_rates(payments, reporting_currency), reporting_currency)
    return aggregate.apply_reporting_currency(payments, reporting_currency, rates)


def _select(scope: AccountScope, account_id: str | None) -> list[Account]:
    if account_id is None:
        return scope.accounts
    accts = [a for a in scope.accounts if a.id == account_id]
    if not accts:
        raise UnknownAccount(account_id)
    return accts


async def _payments(
    accts: list[Account], since: int | None, reporting_currency: str, refresh: bool
) -> list[Payment]:
    per_account = await asyncio.gather(*(fetch.payments_since(a, since, refresh) for a in accts))
    return await _to_reporting([p for ps in per_account for p in ps], reporting_currency)


async def _subscriptions(accts: list[Account], refresh: bool) -> list[Subscription]:
    per_account = await asyncio.gather(*(fetch.subscriptions(a, refresh) for a in accts))
    return [s for ss in per_account for s in ss]


async def accounts() -> AccountsResponse:
    scope = await get_scope()
    return AccountsResponse(
        reporting_currency=scope.reporting_currency,
        accounts=[
            AccountOut(
                id=a.id,
                display_name=a.display_name,
                settlement_currency=a.settlement_currency,
                access=a.access,
            )
            for a in scope.accounts
        ],
    )


async def leaderboard(
    period: Period, limit: int, account_id: str | None, refresh: bool
) -> LeaderboardResponse:
    scope = await get_scope(refresh=refresh)
    accts = _select(scope, account_id)
    since = aggregate.period_start(period)
    payments = await _payments(accts, since, scope.reporting_currency, refresh)
    ranked = aggregate.rank_customers(payments, since)[:limit]

    return LeaderboardResponse(
        period=period,
        since=since,
        reporting_currency=scope.reporting_currency,
        unconverted_count=aggregate.unconverted_count(payments),
        customers=[
            LeaderboardEntry(
                rank=i,
                email=r.email,
                customer_id=customer_id(r.email),
                net_total=r.net_total,
                payment_count=r.payment_count,
                last_seen=r.last_seen,
                accounts=sorted(r.accounts),
            )
            for i, r in enumerate(ranked, start=1)
        ],
    )


async def _subscriptions_if_permitted(accts: list[Account]) -> list[Subscription]:
    try:
        return await _subscriptions(accts, refresh=False)
    except MissingPermission:
        return []


async def customer_profile(cid: str) -> CustomerProfileResponse:
    scope = await get_scope()
    # Filter the full payment history rather than using Stripe Search: search can't query billing
    # or receipt emails, and filtering matches the leaderboard's email attribution exactly.
    # The history is cached, so this is shared with the "all time" leaderboard.
    per_account, subs = await asyncio.gather(
        asyncio.gather(*(fetch.payments_since(a, None) for a in scope.accounts)),
        # Subscribers who haven't paid yet (e.g. on a trial) are linked from the lists too.
        _subscriptions_if_permitted(scope.accounts),
    )
    all_payments = [p for ps in per_account for p in ps]
    email = resolve(cid, [p.email for p in all_payments] + [s.email for s in subs])
    if email is None:
        raise UnknownCustomer(cid)
    payments = aggregate.customer_payments(all_payments, email)
    payments = await _to_reporting(payments, scope.reporting_currency)

    return CustomerProfileResponse(
        email=email,
        customer_id=cid,
        reporting_currency=scope.reporting_currency,
        summary=CustomerSummary(**aggregate.customer_summary(payments)),
        timeline=[TimelineEventOut(**asdict(e)) for e in aggregate.timeline(payments)],
    )


async def cancellations(window: Window, account_id: str | None, refresh: bool) -> CancellationsResponse:
    scope = await get_scope(refresh=refresh)
    accts = _select(scope, account_id)
    since = aggregate.window_start(window)
    # Lifetime value needs the full payment history (cached, and shared with the profile page).
    payments, subs = await asyncio.gather(
        _payments(accts, None, scope.reporting_currency, refresh), _subscriptions(accts, refresh)
    )
    ltv = {r.email: r.net_total for r in aggregate.rank_customers(payments, None)}
    now = int(datetime.now(UTC).timestamp())

    return CancellationsResponse(
        window=window,
        since=since,
        reporting_currency=scope.reporting_currency,
        customers=[
            CancellationEntry(
                email=c.sub.email,
                customer_id=customer_id(c.sub.email),
                account_id=c.sub.account_id,
                plan=c.sub.plan,
                started=c.sub.started,
                canceled_at=c.sub.canceled_at,
                ends_at=c.sub.ends_at,
                ended=not c.sub.current or (c.sub.ends_at is not None and c.sub.ends_at <= now),
                reason=c.sub.cancel_reason,
                feedback=c.sub.cancel_feedback,
                lifetime_value=ltv.get(c.sub.email, 0),
                resubscribed=c.resubscribed,
            )
            for c in aggregate.cancellations(subs, since)
        ],
    )


async def anniversaries(window: Window, account_id: str | None, refresh: bool) -> AnniversariesResponse:
    scope = await get_scope(refresh=refresh)
    accts = _select(scope, account_id)
    now = datetime.now(UTC)
    since = aggregate.window_start(window, now)
    payments, subs = await asyncio.gather(
        _payments(accts, None, scope.reporting_currency, refresh), _subscriptions(accts, refresh)
    )
    ranks = aggregate.rank_customers(payments, None)

    return AnniversariesResponse(
        window=window,
        since=since,
        reporting_currency=scope.reporting_currency,
        customers=[
            AnniversaryEntry(
                email=a.customer.email,
                customer_id=customer_id(a.customer.email),
                years=a.years,
                anniversary=a.date,
                first_paid=a.customer.first_seen,
                last_paid=a.customer.last_seen,
                lifetime_value=a.customer.net_total,
                payment_count=a.customer.payment_count,
                subscribed=a.subscribed,
                accounts=sorted(a.customer.accounts),
            )
            for a in aggregate.anniversaries(ranks, subs, since, int(now.timestamp()))
        ],
    )


async def new_subscribers(window: Window, account_id: str | None, refresh: bool) -> NewSubscribersResponse:
    scope = await get_scope(refresh=refresh)
    accts = _select(scope, account_id)
    since = aggregate.window_start(window)
    subs = await _subscriptions(accts, refresh)

    return NewSubscribersResponse(
        window=window,
        since=since,
        customers=[
            NewSubscriberEntry(
                email=n.sub.email,
                customer_id=customer_id(n.sub.email),
                account_id=n.sub.account_id,
                plan=n.sub.plan,
                started=n.sub.started,
                status=n.sub.status,
                returning=n.returning,
            )
            for n in aggregate.new_subscriptions(subs, since)
        ],
    )
