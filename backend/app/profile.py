"""The writer's profile: which of their plans is Founding, and where their payments come from.

Stoke guesses both from the Stripe data; the writer confirms or corrects them in Settings, and the
actions (app/actions.py) use what's confirmed in place of the guess.
"""

import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.actions import NEWSLETTER, OTHER, Labels, RevenueSource, founding_prices, is_founding
from app.aggregate import Payment, Subscription
from app.auth import CurrentUser
from app.db_models import WriterProfile


class ProfileError(Exception):
    """The label can't be saved; the message is safe to show the user."""


# ---- Reading and saving ----

async def labels(session: AsyncSession, user: CurrentUser) -> Labels:
    p = await session.get(WriterProfile, user.id)
    return Labels(plans=dict(p.plan_labels), applications=dict(p.application_labels)) if p else Labels()


async def _profile(session: AsyncSession, user: CurrentUser) -> WriterProfile:
    p = await session.get(WriterProfile, user.id)
    if p is None:
        p = WriterProfile(user_id=user.id, plan_labels={}, application_labels={})
        session.add(p)
    return p


async def set_plan_label(session: AsyncSession, user: CurrentUser, price_id: str, label: str | None) -> None:
    p = await _profile(session, user)
    plans = {k: v for k, v in p.plan_labels.items() if k != price_id}
    if label is not None:
        plans[price_id] = label
    p.plan_labels = plans  # a new dict, so the JSONB column is saved
    await session.commit()


async def set_application_label(
    session: AsyncSession, user: CurrentUser, application: str, label: str | None, sources: list[RevenueSource]
) -> None:
    if label not in (None, NEWSLETTER, OTHER) and label not in {s.id for s in sources}:
        raise ProfileError("That isn't one of your revenue streams.")
    p = await _profile(session, user)
    apps = {k: v for k, v in p.application_labels.items() if k != application}
    if label is not None:
        apps[application] = label
    p.application_labels = apps
    await session.commit()


# ---- Plans ----

@dataclass(frozen=True)
class Plan:
    price_id: str
    account_id: str
    name: str | None
    amount: int | None
    currency: str | None
    interval: str | None
    interval_count: int | None
    subscribers: int  # current subscriptions on this price
    label: str | None  # confirmed: standard | founding
    suggested: str  # the guess, used until it's confirmed


def plans(subs: list[Subscription], labels: Labels) -> list[Plan]:
    """Every price subscribed to, most subscribers first. Subscriptions stored before prices were
    kept have no price, and aren't listed."""
    by_price: dict[str, list[Subscription]] = {}
    for s in subs:
        if s.price_id:
            by_price.setdefault(s.price_id, []).append(s)
    founding = founding_prices(subs)
    out = []
    for price_id, own in by_price.items():
        latest = max(own, key=lambda s: s.started)
        out.append(Plan(
            price_id=price_id, account_id=latest.account_id,
            name=Counter(s.plan for s in own if s.plan).most_common(1)[0][0] if any(s.plan for s in own) else None,
            amount=latest.price_amount, currency=latest.price_currency,
            interval=latest.interval, interval_count=latest.interval_count,
            subscribers=sum(1 for s in own if s.current),
            label=labels.plans.get(price_id),
            suggested="founding" if is_founding(latest, founding) else "standard",
        ))
    return sorted(out, key=lambda p: (-p.subscribers, p.account_id, p.amount or 0, p.price_id))


# ---- Where payments come from ----

@dataclass(frozen=True)
class PaymentSource:
    application: str  # the Connect application id
    account_ids: list[str]
    platform: str | None  # its name, from its application fee's label, e.g. "Substack"
    payments: int
    customers: int
    last_paid: int
    example: str | None  # what the latest payment was for
    label: str | None  # confirmed: a revenue source's id, newsletter, or other
    suggested: str | None


_FEE_SUFFIX = re.compile(r"\s*(application|platform)?\s*fees?$", re.IGNORECASE)


def platform_name(payments: list[Payment]) -> str | None:
    """The platform's own label on its application fee, e.g. "Substack application fee" -> "Substack"."""
    for p in reversed(payments):
        for f in p.settled_fees:
            if f.type == "application_fee" and f.description:
                return _FEE_SUFFIX.sub("", f.description).strip() or None
    return None


def _suggest(platform: str | None, sources: list[RevenueSource]) -> str | None:
    name = (platform or "").lower()
    if not name:
        return None
    if "substack" in name:
        return NEWSLETTER
    for src in sources:
        if src.kind != "other" and src.kind in name:
            return src.id
    return None


def payment_sources(payments: list[Payment], sources: list[RevenueSource], labels: Labels) -> list[PaymentSource]:
    """Every Connect application that has taken a successful payment, most payments first."""
    by_app: dict[str, list[Payment]] = {}
    for p in sorted(payments, key=lambda p: p.created):
        if p.application and p.countable:
            by_app.setdefault(p.application, []).append(p)
    known = {s.id for s in sources} | {NEWSLETTER, OTHER}  # a deleted revenue source's label no longer counts
    out = []
    for app, own in by_app.items():
        platform = platform_name(own)
        out.append(PaymentSource(
            application=app, account_ids=sorted({p.account_id for p in own}), platform=platform,
            payments=len(own), customers=len({p.email for p in own if p.email}), last_paid=own[-1].created,
            example=own[-1].description,
            label=label if (label := labels.applications.get(app)) in known else None, suggested=_suggest(platform, sources),
        ))
    return sorted(out, key=lambda s: (-s.payments, s.application))
