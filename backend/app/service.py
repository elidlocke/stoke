import asyncio
from dataclasses import asdict

from app import aggregate, fetch, fx
from app.aggregate import Payment
from app.models import (
    AccountOut,
    AccountsResponse,
    CustomerProfileResponse,
    CustomerSummary,
    LeaderboardEntry,
    LeaderboardResponse,
    Period,
    TimelineEventOut,
)
from app.stripe_client import get_scope


class UnknownAccount(Exception):
    pass


async def _to_reporting(payments: list[Payment], reporting_currency: str) -> list[Payment]:
    rates = await fx.get_rates(aggregate.needed_rates(payments, reporting_currency), reporting_currency)
    return aggregate.apply_reporting_currency(payments, reporting_currency, rates)


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
    accts = scope.accounts
    if account_id is not None:
        accts = [a for a in accts if a.id == account_id]
        if not accts:
            raise UnknownAccount(account_id)

    since = aggregate.period_start(period)
    per_account = await asyncio.gather(*(fetch.payments_since(a, since, refresh) for a in accts))
    payments = await _to_reporting([p for ps in per_account for p in ps], scope.reporting_currency)
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
                net_total=r.net_total,
                payment_count=r.payment_count,
                last_seen=r.last_seen,
                accounts=sorted(r.accounts),
            )
            for i, r in enumerate(ranked, start=1)
        ],
    )


async def customer_profile(email: str) -> CustomerProfileResponse:
    scope = await get_scope()
    # Filter the full payment history rather than using Stripe Search: search can't query billing
    # or receipt emails, and filtering matches the leaderboard's email attribution exactly.
    # The history is cached, so this is shared with the "all time" leaderboard.
    per_account = await asyncio.gather(*(fetch.payments_since(a, None) for a in scope.accounts))
    payments = aggregate.customer_payments([p for ps in per_account for p in ps], email)
    payments = await _to_reporting(payments, scope.reporting_currency)

    return CustomerProfileResponse(
        email=email,
        reporting_currency=scope.reporting_currency,
        summary=CustomerSummary(**aggregate.customer_summary(payments)),
        timeline=[TimelineEventOut(**asdict(e)) for e in aggregate.timeline(payments)],
    )
