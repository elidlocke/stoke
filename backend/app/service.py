import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app import actions as library
from app import aggregate, fetch, fx, outreach, profile, sync, templates
from app.aggregate import Payment, Subscription
from app.models import (
    AccountOut,
    ActionAudienceResponse,
    ActionOut,
    ActionsResponse,
    AccountsResponse,
    AccountSyncOut,
    AnniversariesResponse,
    AnniversaryEntry,
    AtRiskEntry,
    AtRiskResponse,
    AudienceEntry,
    CancellationEntry,
    CancellationsResponse,
    CustomerProfileResponse,
    CustomerSummary,
    LeaderboardEntry,
    LeaderboardResponse,
    MergeFieldOut,
    NewCustomerEntry,
    NewCustomersResponse,
    NoteOut,
    NotePart,
    ObjectSyncOut,
    PaymentSourceOut,
    PaymentSourcesResponse,
    PlanOut,
    PlansResponse,
    Period,
    PreviewReader,
    PreviewResponse,
    QueueEntry,
    QueueResponse,
    SyncStatusResponse,
    TemplateOut,
    TimelineEventOut,
    TrendMonthOut,
    TrendsResponse,
    Window,
)
from app.auth import CurrentUser
from app.db_models import WriterAction
from app.customer_id import customer_id, ref_id, resolve
from app.stripe_client import Account, AccountScope, MissingPermission, get_scope


class UnknownAccount(Exception):
    pass


class UnknownCustomer(Exception):
    pass


class UnknownAction(Exception):
    pass


class UnknownRef(Exception):
    """An opaque plan or payment-source id that matches none of the user's."""


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


async def accounts(user: CurrentUser) -> AccountsResponse:
    scope = await get_scope(user)
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


async def sync_status(user: CurrentUser) -> SyncStatusResponse:
    scope = await get_scope(user)
    states = await sync.progress((a.id, a.livemode) for a in scope.accounts)
    return SyncStatusResponse(accounts=[
        AccountSyncOut(
            id=a.id,
            display_name=a.display_name,
            state=(s := states[(a.id, a.livemode)]).state,
            objects=[ObjectSyncOut(object=o.object, state=o.state, count=o.count) for o in s.objects],
        )
        for a in scope.accounts
    ])


async def leaderboard(
    user: CurrentUser, period: Period, limit: int, account_id: str | None, refresh: bool
) -> LeaderboardResponse:
    scope = await get_scope(user, refresh=refresh)
    accts = _select(scope, account_id)
    since = aggregate.period_start(period)
    payments = await _payments(accts, since, scope.reporting_currency, refresh)
    all_ranked = aggregate.rank_customers(payments, since)
    ranked = all_ranked[:limit]

    return LeaderboardResponse(
        period=period,
        since=since,
        reporting_currency=scope.reporting_currency,
        unconverted_count=aggregate.unconverted_count(payments),
        customer_count=len(all_ranked),
        customers=[
            LeaderboardEntry(
                rank=i,
                email=r.email,
                customer_id=customer_id(r.email),
                take_home=r.take_home,
                payment_count=r.payment_count,
                last_seen=r.last_seen,
                accounts=sorted(r.accounts),
            )
            for i, r in enumerate(ranked, start=1)
        ],
    )


async def _subscriptions_if_permitted(accts: list[Account], refresh: bool = False) -> list[Subscription]:
    try:
        return await _subscriptions(accts, refresh)
    except MissingPermission:
        return []


async def customer_profile(user: CurrentUser, cid: str) -> CustomerProfileResponse:
    scope = await get_scope(user)
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


async def cancellations(
    user: CurrentUser, window: Window, account_id: str | None, refresh: bool
) -> CancellationsResponse:
    scope = await get_scope(user, refresh=refresh)
    accts = _select(scope, account_id)
    since = aggregate.window_start(window)
    # Lifetime value needs the full payment history (cached, and shared with the profile page).
    payments, subs = await asyncio.gather(
        _payments(accts, None, scope.reporting_currency, refresh), _subscriptions(accts, refresh)
    )
    ltv = {r.email: r.take_home for r in aggregate.rank_customers(payments, None)}
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
                current_plan=c.current.plan if c.current else None,
                current_since=c.current.started if c.current else None,
            )
            for c in aggregate.cancellations(subs, since)
        ],
    )


async def anniversaries(
    user: CurrentUser, window: Window, account_id: str | None, refresh: bool
) -> AnniversariesResponse:
    scope = await get_scope(user, refresh=refresh)
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
                lifetime_value=a.customer.take_home,
                payment_count=a.customer.payment_count,
                subscribed=a.subscribed,
                accounts=sorted(a.customer.accounts),
            )
            for a in aggregate.anniversaries(ranks, subs, since, int(now.timestamp()))
        ],
    )


async def new_customers(
    user: CurrentUser, window: Window, account_id: str | None, refresh: bool
) -> NewCustomersResponse:
    scope = await get_scope(user, refresh=refresh)
    accts = _select(scope, account_id)
    since = aggregate.window_start(window)
    # The full history, to tell a first purchase from a returning customer. Without Subscriptions
    # access this still lists customers who paid, just not unpaid trials.
    payments, subs = await asyncio.gather(
        _payments(accts, None, scope.reporting_currency, refresh), _subscriptions_if_permitted(accts, refresh)
    )

    return NewCustomersResponse(
        window=window,
        since=since,
        reporting_currency=scope.reporting_currency,
        customers=[
            NewCustomerEntry(customer_id=customer_id(n.email), **asdict(n))
            for n in aggregate.new_customers(payments, subs, since)
        ],
    )


async def at_risk(user: CurrentUser, account_id: str | None, refresh: bool) -> AtRiskResponse:
    scope = await get_scope(user, refresh=refresh)
    accts = _select(scope, account_id)
    # The full history, for disputes on old payments and lifetime value. Without Subscriptions
    # access this still lists disputes.
    payments, subs = await asyncio.gather(
        _payments(accts, None, scope.reporting_currency, refresh), _subscriptions_if_permitted(accts, refresh)
    )
    ltv = {r.email: r.take_home for r in aggregate.rank_customers(payments, None)}
    now = int(datetime.now(UTC).timestamp())

    return AtRiskResponse(
        reporting_currency=scope.reporting_currency,
        customers=[
            AtRiskEntry(customer_id=customer_id(r.email), lifetime_value=ltv.get(r.email, 0), **asdict(r))
            for r in aggregate.at_risk(payments, subs, now)
        ],
    )


async def trends(user: CurrentUser, refresh: bool) -> TrendsResponse:
    scope = await get_scope(user, refresh=refresh)
    # The full history, to tell a first purchase from a returning customer.
    payments = await _payments(scope.accounts, None, scope.reporting_currency, refresh)
    try:
        subs, churn_available = await _subscriptions(scope.accounts, refresh), True
    except MissingPermission:
        subs, churn_available = [], False

    return TrendsResponse(
        reporting_currency=scope.reporting_currency,
        months=[TrendMonthOut(**asdict(m)) for m in aggregate.trends(payments, subs, datetime.now(UTC))],
        churn_available=churn_available,
        unconverted_count=aggregate.unconverted_count(payments),
    )


@dataclass(frozen=True)
class Writer:
    """What the writer has set up, from the database: everything the actions need besides Stripe data."""
    sources: list[library.RevenueSource]
    labels: library.Labels
    socials: list[templates.Social]
    settings: dict[str, WriterAction]  # by action kind; none for actions never changed
    sent: dict[str, int]  # notes marked sent, by action kind


async def _audiences(
    user: CurrentUser, w: Writer, account_id: str | None, refresh: bool, only: str | None = None
) -> tuple[str, list[library.Audience]]:
    scope = await get_scope(user, refresh=refresh)
    accts = _select(scope, account_id)
    payments = await _payments(accts, None, scope.reporting_currency, refresh)
    try:
        subs, subscriptions_available = await _subscriptions(accts, refresh), True
    except MissingPermission:
        subs, subscriptions_available = [], False
    now = int(datetime.now(UTC).timestamp())
    found = library.audiences(payments, subs, w.sources, now, subscriptions_available, only, w.labels)
    return scope.reporting_currency, found


def _action_out(a: library.Audience, w: Writer) -> ActionOut:
    act = a.action
    row = w.settings.get(act.kind)
    return ActionOut(
        kind=act.kind, type=act.type, title=act.title, rule=act.rule, ask=act.ask, link_id=act.link_id,
        unavailable=a.unavailable, audience_size=len(a.candidates),
        enabled=row.enabled if row else False, sent=w.sent.get(act.kind, 0),
    )


async def actions(user: CurrentUser, w: Writer, account_id: str | None, refresh: bool) -> ActionsResponse:
    currency, found = await _audiences(user, w, account_id, refresh)
    return ActionsResponse(reporting_currency=currency, actions=[_action_out(a, w) for a in found])


async def _audience(
    user: CurrentUser, w: Writer, kind: str, account_id: str | None, refresh: bool
) -> tuple[str, library.Audience]:
    currency, found = await _audiences(user, w, account_id, refresh, only=kind)
    if not found:
        raise UnknownAction(kind)
    return currency, found[0]


async def action(user: CurrentUser, w: Writer, kind: str, account_id: str | None, refresh: bool) -> ActionAudienceResponse:
    currency, a = await _audience(user, w, kind, account_id, refresh)
    t = outreach.template(kind, w.settings.get(kind))
    return ActionAudienceResponse(
        reporting_currency=currency,
        action=_action_out(a, w),
        customers=[
            AudienceEntry(
                email=c.email, customer_id=customer_id(c.email), account_id=c.account_id, why=c.why, plan=c.plan,
                lifetime_value=c.lifetime_value, date=c.date, deadline=c.deadline,
            )
            for c in a.candidates
        ],
        template=TemplateOut(
            subject=t.subject, body=t.body, is_default=t.is_default,
            approved_at=int(t.approved_at.timestamp()) if t.approved_at else None,
        ),
        fields=[
            MergeFieldOut(name=f.name, description=f.description, fallback=f.fallback) for f in templates.fields_for(kind)
        ],
    )


def _parts(parts: list[templates.Part]) -> list[NotePart]:
    return [NotePart(text=p.text, field=p.field, fallback=p.fallback) for p in parts]


async def queue(user: CurrentUser, w: Writer, kind: str, done: set[str], account_id: str | None) -> QueueResponse:
    """The action's audience minus anyone in `done` (customer ids already marked for it), each with their note."""
    _, a = await _audience(user, w, kind, account_id, refresh=False)
    row = w.settings.get(kind)
    if row is None or not row.enabled or row.approved_at is None:
        return QueueResponse(open=False, customers=[])
    t = outreach.template(kind, row)
    source = next((s for s in w.sources if s.id == a.action.link_id), None)
    fallbacks = templates.fallbacks(kind)
    entries = []
    for c in a.candidates:
        cid = customer_id(c.email)
        if cid in done:
            continue
        entries.append(QueueEntry(
            email=c.email, customer_id=cid, account_id=c.account_id, why=c.why, plan=c.plan,
            lifetime_value=c.lifetime_value, deadline=c.deadline,
            note=_note(t.subject, t.body, templates.values(c, source, w.socials), fallbacks),
        ))
    return QueueResponse(open=True, customers=entries)


PREVIEW_READERS = 5


def _note(subject: str, body: str, values: dict[str, str], fallbacks: dict[str, str]) -> NoteOut:
    s, b = templates.fill(subject, values, fallbacks), templates.fill(body, values, fallbacks)
    return NoteOut(subject=_parts(s), body=_parts(b), missing=templates.missing(s + b))


async def preview(
    user: CurrentUser, w: Writer, kind: str, subject: str, body: str, account_id: str | None
) -> PreviewResponse:
    """A draft (saved or not) filled in for the first few people in the action's audience, including someone
    without a first name if there is one, so the fallback shows. With nobody in it, for an example reader."""
    _, a = await _audience(user, w, kind, account_id, refresh=False)
    source = next((s for s in w.sources if s.id == a.action.link_id), None)
    fallbacks = templates.fallbacks(kind)
    if not a.candidates:
        note = _note(subject, body, templates.example_values(kind, source, w.socials), fallbacks)
        return PreviewResponse(example=True, readers=[PreviewReader(email=None, customer_id=None, why=None, note=note)])
    readers = a.candidates[:PREVIEW_READERS]
    nameless = next((c for c in a.candidates if not c.fields.get("first_name")), None)
    if nameless is not None and nameless not in readers and len(readers) == PREVIEW_READERS:
        readers = readers[:-1] + [nameless]
    return PreviewResponse(example=False, readers=[
        PreviewReader(
            email=c.email, customer_id=customer_id(c.email), why=c.why,
            note=_note(subject, body, templates.values(c, source, w.socials), fallbacks),
        )
        for c in readers
    ])


async def in_audience(user: CurrentUser, w: Writer, kind: str, cid: str) -> bool:
    _, a = await _audience(user, w, kind, None, refresh=False)
    return any(customer_id(c.email) == cid for c in a.candidates)


async def emails_by_id(user: CurrentUser) -> dict[str, str]:
    """Every customer's email by their opaque id, to show who a stored note went to."""
    scope = await get_scope(user)
    per_account, subs = await asyncio.gather(
        asyncio.gather(*(fetch.payments_since(a, None) for a in scope.accounts)),
        _subscriptions_if_permitted(scope.accounts),
    )
    emails = {p.email for ps in per_account for p in ps if p.email} | {s.email for s in subs if s.email}
    return {customer_id(e): e for e in emails}


def titles(w: Writer) -> dict[str, str]:
    """Every action's title by kind."""
    return {action.kind: action.title for action, _ in library.library(w.sources)}


async def _all_subscriptions(user: CurrentUser) -> list[Subscription]:
    return await _subscriptions_if_permitted((await get_scope(user)).accounts)


async def plans(user: CurrentUser, labels: library.Labels) -> PlansResponse:
    subs = await _all_subscriptions(user)
    return PlansResponse(
        plans=[
            PlanOut(
                id=ref_id("price", p.price_id), account_id=p.account_id, name=p.name, amount=p.amount, currency=p.currency,
                interval=p.interval, interval_count=p.interval_count, subscribers=p.subscribers,
                label=p.label, suggested=p.suggested,
            )
            for p in profile.plans(subs, labels)
        ],
        unpriced=sum(1 for s in subs if s.current and s.price_id is None),
    )


async def price_id(user: CurrentUser, ref: str) -> str:
    """The Stripe price behind an opaque plan id."""
    for s in await _all_subscriptions(user):
        if s.price_id and ref_id("price", s.price_id) == ref:
            return s.price_id
    raise UnknownRef(ref)


async def _all_payments(user: CurrentUser) -> list[Payment]:
    scope = await get_scope(user)
    per_account = await asyncio.gather(*(fetch.payments_since(a, None) for a in scope.accounts))
    return [p for ps in per_account for p in ps]


async def payment_sources(
    user: CurrentUser, sources: list[library.RevenueSource], labels: library.Labels
) -> PaymentSourcesResponse:
    return PaymentSourcesResponse(sources=[
        PaymentSourceOut(
            id=ref_id("application", s.application), account_ids=s.account_ids, platform=s.platform,
            payments=s.payments, customers=s.customers, last_paid=s.last_paid, example=s.example,
            label=s.label, suggested=s.suggested,
        )
        for s in profile.payment_sources(await _all_payments(user), sources, labels)
    ])


async def application_id(user: CurrentUser, ref: str) -> str:
    """The Connect application behind an opaque payment-source id."""
    for app in {p.application for p in await _all_payments(user) if p.application}:
        if ref_id("application", app) == ref:
            return app
    raise UnknownRef(ref)
