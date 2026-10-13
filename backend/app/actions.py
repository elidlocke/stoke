"""The action library: who to reach out to, and why. Pure functions over normalized data; no I/O here.

Each action has an audience rule over the same payments and subscriptions as the analytics, and
every person in an audience carries a "why" a writer can read at a glance. Thresholds are defaults
for now; actions become adjustable once they're stored (see docs/actions-plan.md).

What the writer has confirmed in Settings (Labels) overrides the guesses: which plans are Founding,
and which Connect application each revenue source's payments come from.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from app import aggregate
from app.aggregate import CURRENT_STATUSES, NEVER_STARTED, OPEN_DISPUTE_STATUSES, Payment, Subscription

DAY = 86400

ActionType = Literal["gratitude", "upgrade", "cross_sell", "win_back", "retention"]

# Thresholds (the defaults until a writer can change them).
WELCOME_DAYS = 30
ANNIVERSARY_DAYS = 30
WELCOME_BACK_DAYS = 60
VIP_TOP = 20
FOUNDING_MIN_RENEWALS = 2
ANNUAL_MIN_RENEWALS = 3
CLEAN_PAYMENTS_DAYS = 365  # upgrades: no failed payment in this long
EXPENSIVE_TOP = 25
EXPENSIVE_MIN_RENEWALS = 3
CHEAP_MIN_DAYS = 30
TENURED_DAYS = 365
REPEAT_IDLE_DAYS = 180
WIN_BACK_DAYS = 90
EXCLUDE_REFUND_DAYS = 90

# How a revenue source is pitched, by the platform it's sold on; "other" goes by how it's bought.
CrossSellTier = Literal["expensive", "cheap", "subscription"]
_TIER_BY_KIND: dict[str, CrossSellTier] = {
    "calendly": "expensive", "maven": "expensive", "luma": "expensive",
    "gumroad": "cheap", "teachable": "cheap",
    "circle": "subscription",
}
_TIER_BY_PURCHASE: dict[str, CrossSellTier] = {"repeat": "expensive", "once": "cheap", "subscription": "subscription"}

_FEEDBACK = {
    "customer_service": "customer service",
    "low_quality": "low quality",
    "missing_features": "missing features",
    "switched_service": "switched to something else",
    "too_complex": "too complex",
    "too_expensive": "too expensive",
    "unused": "not using it",
    "other": "another reason",
}

_DISPUTE_REASONS = {
    "fraudulent": "the cardholder says they didn't make it",
    "product_not_received": "product not received",
    "product_unacceptable": "product unacceptable",
    "subscription_canceled": "they say they canceled",
    "duplicate": "a duplicate charge",
    "credit_not_processed": "a refund not processed",
    "unrecognized": "they didn't recognise the charge",
}


PlanLabel = Literal["standard", "founding"]
NEWSLETTER = "newsletter"  # an application's payments are for the newsletter itself (e.g. Substack's)
OTHER = "other"  # neither the newsletter nor one of the writer's revenue sources


@dataclass(frozen=True)
class Labels:
    """What the writer confirmed in Settings (a WriterProfile)."""
    plans: dict[str, str] = field(default_factory=dict)  # price id -> standard | founding
    applications: dict[str, str] = field(default_factory=dict)  # application id -> link id | newsletter | other


@dataclass(frozen=True)
class RevenueSource:
    """What the rules need of a writer's revenue source (a WriterLink)."""
    id: str
    kind: str  # the platform: calendly, maven, ...
    name: str
    purchase: str  # once | repeat | subscription
    paid_via_account_id: str | None  # the connected account it's paid through; None: elsewhere
    # Connect applications the writer confirmed its payments come from. Then exactly its payments are
    # known; otherwise every one-off payment on paid_via_account_id is taken to be one.
    applications: frozenset[str] = frozenset()

    @property
    def payments_known(self) -> bool:
        return bool(self.applications) or self.paid_via_account_id is not None


@dataclass(frozen=True)
class Candidate:
    email: str
    account_id: str
    why: str
    plan: str | None
    lifetime_value: int  # take-home across all time, minor units of the reporting currency
    date: int  # the event that put them here: subscribing, an anniversary, canceling, ...
    deadline: int | None = None  # retention: next retry, when access ends, or the evidence deadline


@dataclass(frozen=True)
class Action:
    kind: str  # e.g. "welcome", or "cross-sell-<link id>" for one per revenue source
    type: ActionType
    title: str
    rule: str  # the audience in words, with its thresholds
    ask: str
    link_id: str | None = None
    needs_subscriptions: bool = True


@dataclass(frozen=True)
class Audience:
    action: Action
    candidates: list[Candidate]
    # Why the audience can't be worked out yet, e.g. no Founding plan was found. Then it's empty.
    unavailable: str | None = None


# ---- Wording ----

def _date(ts: int) -> str:
    d = datetime.fromtimestamp(ts, UTC)
    return f"{d.day} {d:%b %Y}"


def _month(ts: int) -> str:
    return f"{datetime.fromtimestamp(ts, UTC):%b %Y}"


def _span(seconds: int) -> str:
    days = max(seconds // DAY, 0)
    if days < 1:
        return "less than a day"
    if days < 14:
        return f"{days} day{'s' if days != 1 else ''}"
    if days < 60:
        return f"{days // 7} weeks"
    if days < 730:
        return f"{days // 30} months"
    return f"{days // 365} years"


def _ago(ts: int, now: int) -> str:
    return "today" if now - ts < DAY else f"{_span(now - ts)} ago"


def _in(ts: int, now: int) -> str:
    return "today" if 0 <= ts - now < DAY else ("overdue" if ts < now else f"in {_span(ts - now)}")


def _times(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


# ---- What the rules share ----

@dataclass
class Facts:
    """Everything the rules read, worked out once from the payments and subscriptions."""
    payments: list[Payment]
    subs: list[Subscription]
    now: int
    labels: Labels = field(default_factory=Labels)
    ranks: list[aggregate.CustomerRank] = field(init=False)
    ltv: dict[str, int] = field(init=False)
    rank_of: dict[str, int] = field(init=False)
    staying: dict[str, list[Subscription]] = field(init=False)  # current and not canceling, per email
    renewals: dict[tuple[str, str], int] = field(init=False)  # (email, account)
    recent_failures: set[str] = field(init=False)
    excluded: set[str] = field(init=False)
    purchases: dict[tuple[str, str], list[Payment]] = field(init=False)  # one-off payments, (email, account)
    founding_prices: set[str] = field(init=False)

    def __post_init__(self) -> None:
        self.ranks = aggregate.rank_customers(self.payments, None)
        self.ltv = {r.email: r.take_home for r in self.ranks}
        self.rank_of = {r.email: i for i, r in enumerate(self.ranks, start=1)}
        self.staying = {}
        for s in self.subs:
            if s.email is not None and s.current and s.canceled_at is None:
                self.staying.setdefault(s.email, []).append(s)
        self.renewals, self.purchases = {}, {}
        self.recent_failures, self.excluded = set(), set()
        for p in sorted(self.payments, key=lambda p: p.created):
            if p.email is None:
                continue
            if p.status == "failed" and p.created >= self.now - CLEAN_PAYMENTS_DAYS * DAY:
                self.recent_failures.add(p.email)
            if not p.countable:
                continue
            if p.billing_reason == "subscription_cycle":
                self.renewals[(p.email, p.account_id)] = self.renewals.get((p.email, p.account_id), 0) + 1
            elif not (p.billing_reason or "").startswith("subscription") and not self._newsletter(p):
                self.purchases.setdefault((p.email, p.account_id), []).append(p)
            if _excluded(p, self.now):
                self.excluded.add(p.email)
        self.founding_prices = founding_prices(self.subs)

    def _newsletter(self, p: Payment) -> bool:
        """Made by the newsletter's platform, e.g. a Substack gift subscription: not a revenue source's sale."""
        return p.application is not None and self.labels.applications.get(p.application) == NEWSLETTER

    def founding(self, s: Subscription) -> bool:
        if s.price_id is not None and s.price_id in self.labels.plans:
            return self.labels.plans[s.price_id] == "founding"
        return is_founding(s, self.founding_prices)

    def has_founding_plan(self) -> bool:
        return any(self.founding(s) for s in self.subs) or "founding" in self.labels.plans.values()

    def source_payments(self, source: RevenueSource) -> dict[str, list[Payment]]:
        """A revenue source's sales by email, oldest first: from its confirmed applications when there are
        any, else every one-off payment on the account it's paid through."""
        if source.applications:
            out: dict[str, list[Payment]] = {}
            for p in sorted(self.payments, key=lambda p: p.created):
                if p.countable and p.email is not None and p.application in source.applications:
                    out.setdefault(p.email, []).append(p)
            return out
        return {email: bought for (email, a), bought in self.purchases.items() if a == source.paid_via_account_id}

    def candidate(self, email: str, account_id: str, why: str, plan: str | None, date: int, deadline: int | None = None) -> Candidate:
        return Candidate(
            email=email, account_id=account_id, why=why, plan=plan,
            lifetime_value=self.ltv.get(email, 0), date=date, deadline=deadline,
        )


def _excluded(p: Payment, now: int) -> bool:
    """An open dispute, or a full refund recently: left out of every action but Dispute check-in."""
    if p.dispute is not None and p.dispute.status in OPEN_DISPUTE_STATUSES:
        return True
    fully_refunded = p.amount > 0 and p.amount_refunded >= p.amount
    return fully_refunded and any(r.created >= now - EXCLUDE_REFUND_DAYS * DAY for r in p.refunds)


def founding_prices(subs: list[Subscription]) -> set[str]:
    """Until the writer labels their plans: on an account with more than one yearly price (in a
    currency), the highest is taken to be Founding, as on Substack."""
    yearly: dict[tuple[str, str], dict[str, int]] = {}
    for s in subs:
        if s.interval == "year" and s.price_id and s.price_amount is not None and s.price_currency:
            yearly.setdefault((s.account_id, s.price_currency), {})[s.price_id] = s.price_amount
    out: set[str] = set()
    for prices in yearly.values():
        if len(set(prices.values())) > 1:
            top = max(prices.values())
            out |= {pid for pid, amount in prices.items() if amount == top}
    return out


def is_founding(s: Subscription, founding: set[str]) -> bool:
    return "founding" in (s.plan or "").lower() or (s.price_id is not None and s.price_id in founding)


def is_monthly(s: Subscription) -> bool:
    if s.interval is not None:
        return s.interval == "month" and (s.interval_count or 1) == 1
    return "monthly" in (s.plan or "").lower()  # stored before prices were kept


def is_yearly(s: Subscription) -> bool:
    if s.interval is not None:
        return s.interval == "year"
    plan = (s.plan or "").lower()
    return "yearly" in plan or "annual" in plan


def _by_value(cs: list[Candidate]) -> list[Candidate]:
    """One entry per person (their first), highest lifetime value first."""
    seen: dict[str, Candidate] = {}
    for c in cs:
        seen.setdefault(c.email, c)
    return sorted(seen.values(), key=lambda c: (-c.lifetime_value, -c.date, c.email))


def _staying_one(f: Facts, email: str) -> Subscription:
    return max(f.staying[email], key=lambda s: s.started)


# ---- The rules ----

def welcome(f: Facts) -> list[Candidate]:
    since = f.now - WELCOME_DAYS * DAY
    return _by_value([
        f.candidate(n.email, n.account_id, f"New paid subscriber, {_ago(n.first_seen, f.now)}", n.description, n.first_seen)
        for n in aggregate.new_customers(f.payments, f.subs, since)
        if n.started_with == "subscription" and n.subscription_status in CURRENT_STATUSES - {"trialing"}
    ])


def anniversary(f: Facts) -> list[Candidate]:
    since = f.now - ANNIVERSARY_DAYS * DAY
    out = []
    for a in aggregate.anniversaries(f.ranks, f.subs, since, f.now):
        # Thanked once the renewal around the anniversary has gone through, never before.
        if not a.subscribed or a.customer.last_seen < a.date - 3 * DAY:
            continue
        sub = max((s for s in f.subs if s.email == a.customer.email and s.current), key=lambda s: s.started)
        why = f"{_times(a.years, 'year')} since their first payment, on {_date(a.date)}"
        out.append(f.candidate(a.customer.email, sub.account_id, why, sub.plan, a.date))
    return _by_value(out)


def welcome_back(f: Facts) -> list[Candidate]:
    since = f.now - WELCOME_BACK_DAYS * DAY
    out = []
    for c in aggregate.cancellations(f.subs, 0):
        if c.resubscribed and c.current is not None and c.current.started >= since:
            why = f"Came back {_ago(c.current.started, f.now)}, after canceling in {_month(c.sub.canceled_at or c.sub.started)}"
            out.append(f.candidate(c.current.email or "", c.current.account_id, why, c.current.plan, c.current.started))
    return _by_value(out)


def vip(f: Facts) -> list[Candidate]:
    subscribed = {s.email: s for s in sorted(f.subs, key=lambda s: s.started) if s.email and s.current}
    top = [r for r in f.ranks if r.email in subscribed][:VIP_TOP]
    out = [
        f.candidate(r.email, subscribed[r.email].account_id, f"#{f.rank_of[r.email]} of all customers by lifetime take-home",
                    subscribed[r.email].plan, r.last_seen)
        for r in top
    ]
    for s in f.subs:
        if s.email and s.current and f.founding(s):
            out.append(f.candidate(s.email, s.account_id, f"Founding member since {_month(s.started)}", s.plan, s.started))
    return _by_value(out)


def _upgradable(f: Facts, min_renewals: int, fits: Callable[[Subscription], bool]) -> list[tuple[Subscription, int]]:
    out = []
    for email, subs in f.staying.items():
        if email in f.recent_failures or any(f.founding(s) for s in subs):
            continue
        s = _staying_one(f, email)
        renewals = f.renewals.get((email, s.account_id), 0)
        if fits(s) and renewals >= min_renewals:
            out.append((s, renewals))
    return out


def founding_upgrade(f: Facts) -> list[Candidate]:
    return _by_value([
        f.candidate(s.email or "", s.account_id,
                    f"{_times(n, 'renewal')} since {_month(s.started)}, no failed payments", s.plan, s.started)
        for s, n in _upgradable(f, FOUNDING_MIN_RENEWALS, lambda s: True)
    ])


def monthly_to_annual(f: Facts) -> list[Candidate]:
    return _by_value([
        f.candidate(s.email or "", s.account_id,
                    f"Monthly for {_span(f.now - s.started)}, {_times(n, 'renewal')}, no failed payments", s.plan, s.started)
        for s, n in _upgradable(f, ANNUAL_MIN_RENEWALS, is_monthly)
        if not any(is_yearly(o) for o in f.staying[s.email or ""])
    ])


def cross_sell_tier(source: RevenueSource) -> CrossSellTier:
    return _TIER_BY_KIND.get(source.kind) or _TIER_BY_PURCHASE.get(source.purchase, "cheap")


def _buyers(f: Facts, source: RevenueSource) -> set[str]:
    """Who has already bought it: only knowable when its payments can be found in Stripe."""
    if not source.payments_known:
        return set()
    out = set(f.source_payments(source))
    if source.purchase == "subscription" and not source.applications:
        acct = source.paid_via_account_id
        out |= {s.email for s in f.subs if s.email and s.account_id == acct and s.status not in NEVER_STARTED}
    return out


def cross_sell(f: Facts, source: RevenueSource) -> list[Candidate]:
    buyers = _buyers(f, source)
    tier = cross_sell_tier(source)
    out = []
    if tier == "expensive":
        for email in sorted(f.staying, key=lambda e: (-f.ltv.get(e, 0), e)):
            s = _staying_one(f, email)
            n = f.renewals.get((email, s.account_id), 0)
            if email not in buyers and n >= EXPENSIVE_MIN_RENEWALS:
                why = f"#{f.rank_of[email]} by lifetime take-home, {_times(n, 'renewal')}" if email in f.rank_of else f"{_times(n, 'renewal')}"
                out.append(f.candidate(email, s.account_id, why, s.plan, s.started))
            if len(out) >= EXPENSIVE_TOP:
                break
    elif tier == "cheap":
        for email in f.staying:
            s = min(f.staying[email], key=lambda s: s.started)
            if email not in buyers and s.started <= f.now - CHEAP_MIN_DAYS * DAY:
                out.append(f.candidate(email, s.account_id, f"Paid subscriber since {_month(s.started)}", s.plan, s.started))
    else:
        for email in f.staying:
            for s in f.staying[email]:
                if email in buyers or s.started > f.now - TENURED_DAYS * DAY:
                    continue
                if f.founding(s):
                    why = f"Founding member for {_span(f.now - s.started)}"
                elif is_yearly(s):
                    why = f"Annual subscriber for {_span(f.now - s.started)}"
                else:
                    continue
                out.append(f.candidate(email, s.account_id, why, s.plan, s.started))
    return _by_value(out)


def repeat_booking(f: Facts, source: RevenueSource) -> list[Candidate]:
    out = []
    for email, bought in f.source_payments(source).items():
        last = bought[-1]
        if last.created <= f.now - REPEAT_IDLE_DAYS * DAY:
            why = f"Bought {_times(len(bought), 'time')}, last {_ago(last.created, f.now)}"
            out.append(f.candidate(email, last.account_id, why, last.description, last.created))
    return _by_value(out)


def win_back(f: Facts) -> list[Candidate]:
    since = f.now - WIN_BACK_DAYS * DAY
    out = []
    for c in aggregate.cancellations(f.subs, since):
        s = c.sub
        ended = not s.current or (s.ends_at is not None and s.ends_at <= f.now)
        involuntary = s.cancel_reason in ("payment_failed", "payment_disputed")
        if not ended or involuntary or c.current is not None or (s.email or "") in f.staying:
            continue
        reason = _FEEDBACK.get(s.cancel_feedback or "", "no reason given")
        out.append(f.candidate(s.email or "", s.account_id, f"Canceled {_ago(s.canceled_at or 0, f.now)}: {reason}", s.plan,
                               s.canceled_at or 0))
    return _by_value(out)


def _at_risk(f: Facts, kinds: set[str]) -> list[Candidate]:
    """In the at-risk order: the most urgent deadline first."""
    out, seen = [], set()
    for r in aggregate.at_risk(f.payments, f.subs, f.now):
        if r.kind not in kinds or (r.kind, r.email) in seen:
            continue
        seen.add((r.kind, r.email))
        out.append(f.candidate(r.email, r.account_id, _risk_why(r, f.now), r.plan, r.since, r.deadline))
    return out


def _risk_why(r: aggregate.AtRisk, now: int) -> str:
    match r.kind:
        case "canceling":
            reason = _FEEDBACK.get(r.feedback or "")
            ends = f"access ends {_in(r.deadline, now)}" if r.deadline else "still subscribed"
            return f"Canceling, {ends}" + (f": {reason}" if reason else "")
        case "payment_failing":
            retry = f"next retry {_in(r.deadline, now)}" if r.deadline else "no retry scheduled"
            return f"Payment failing since {_date(r.since)}, {retry}"
        case "retries_exhausted":
            return f"Payment failed {_ago(r.since, now)}, and Stripe has stopped retrying"
        case "lapsed":
            return f"Subscription ended {_ago(r.since, now)} after a failed payment"
        case _:
            reason = _DISPUTE_REASONS.get(r.dispute_reason or "")
            respond = f"respond by {_date(r.deadline)}" if r.deadline else "no deadline"
            return f"Dispute opened {_ago(r.since, now)}" + (f" ({reason})" if reason else "") + f", {respond}"


def save(f: Facts) -> list[Candidate]:
    return _at_risk(f, {"canceling"})


def card_failing(f: Facts) -> list[Candidate]:
    return _at_risk(f, {"payment_failing", "retries_exhausted", "lapsed"})


def dispute_check_in(f: Facts) -> list[Candidate]:
    return _at_risk(f, {"dispute"})


# ---- The library ----

_FIXED: list[tuple[Action, Callable[[Facts], list[Candidate]]]] = [
    (Action("welcome", "gratitude", "Welcome",
            f"Started a paid subscription in the last {WELCOME_DAYS} days.",
            "Reply and say hi; your social links."), welcome),
    (Action("anniversary", "gratitude", "Anniversary thank-you",
            f"Still subscribed, with a paid anniversary in the last {ANNIVERSARY_DAYS} days and the renewal through.",
            "None, just thanks."), anniversary),
    (Action("welcome-back", "gratitude", "Welcome back",
            f"Resubscribed in the last {WELCOME_BACK_DAYS} days after canceling.",
            "None, just thanks."), welcome_back),
    (Action("vip", "gratitude", "VIP / testimonial",
            f"Top {VIP_TOP} by lifetime take-home and still subscribed, or any current Founding member.",
            "A testimonial."), vip),
    (Action("founding-upgrade", "upgrade", "Founding upgrade",
            f"Current non-Founding subscriber, at least {FOUNDING_MIN_RENEWALS} renewals, no failed payments in 12 months.",
            "Become a Founding member."), founding_upgrade),
    (Action("monthly-to-annual", "upgrade", "Monthly → annual",
            f"Current monthly subscriber, at least {ANNUAL_MIN_RENEWALS} renewals, no failed payments in 12 months.",
            "Switch to annual."), monthly_to_annual),
]

_RETENTION: list[tuple[Action, Callable[[Facts], list[Candidate]]]] = [
    (Action("win-back", "win_back", "Win-back",
            f"Canceled by choice (not a failed payment), ended in the last {WIN_BACK_DAYS} days, and not back.",
            "Come back: a discount if it was too expensive, your best posts if unused."), win_back),
    (Action("save", "retention", "Save",
            "Canceling at the end of the period, still subscribed until then.", "Stay."), save),
    (Action("card-failing", "retention", "Card failing",
            "A payment failing, retries over, or lapsed after a failed payment in the last 30 days.",
            "Update their card: a helpful heads-up, not a pitch."), card_failing),
    (Action("dispute-check-in", "retention", "Dispute check-in",
            "An open dispute or inquiry waiting on your response, soonest deadline first.",
            "Offer to cancel and refund directly, and ask them to withdraw the dispute.",
            needs_subscriptions=False), dispute_check_in),
]

_TIER_RULES: dict[CrossSellTier, str] = {
    "expensive": f"Top {EXPENSIVE_TOP} current subscribers by lifetime take-home, with at least {EXPENSIVE_MIN_RENEWALS} renewals.",
    "cheap": f"Current paid subscribers, {CHEAP_MIN_DAYS}+ days after subscribing.",
    "subscription": "Annual and Founding members subscribed for a year or more.",
}


def _source_actions(sources: list[RevenueSource]) -> list[tuple[Action, Callable[[Facts], list[Candidate]]]]:
    out: list[tuple[Action, Callable[[Facts], list[Candidate]]]] = []
    for src in sources:
        known = " Leaves out anyone who's already bought it." if src.payments_known else ""
        out.append((
            Action(f"cross-sell-{src.id}", "cross_sell", f"Cross-sell: {src.name}", _TIER_RULES[cross_sell_tier(src)] + known,
                   f"{src.name}, with its link.", link_id=src.id),
            lambda f, src=src: cross_sell(f, src),
        ))
        if src.purchase == "repeat" and src.payments_known:
            out.append((
                Action(f"repeat-booking-{src.id}", "cross_sell", f"Repeat booking: {src.name}",
                       f"Bought it before, nothing in {REPEAT_IDLE_DAYS}+ days.",
                       f"Book {src.name} again.", link_id=src.id, needs_subscriptions=False),
                lambda f, src=src: repeat_booking(f, src),
            ))
    return out


def library(sources: list[RevenueSource]) -> list[tuple[Action, Callable[[Facts], list[Candidate]]]]:
    """Every action, in the order the library lists them."""
    return _FIXED + _source_actions(sources) + _RETENTION


def audience(
    action: Action, rule: Callable[[Facts], list[Candidate]], facts: Facts, subscriptions_available: bool
) -> Audience:
    if action.needs_subscriptions and not subscriptions_available:
        return Audience(action, [], "Needs read access to Subscriptions on your Stripe key.")
    if action.kind == "founding-upgrade" and not facts.has_founding_plan():
        return Audience(action, [], "No Founding plan found among your subscriptions.")
    people = rule(facts)
    if action.kind != "dispute-check-in":
        people = [c for c in people if c.email not in facts.excluded]
    return Audience(action, people)


def with_applications(sources: list[RevenueSource], labels: Labels) -> list[RevenueSource]:
    """Each revenue source with the applications the writer confirmed for it."""
    return [
        replace(src, applications=frozenset(app for app, label in labels.applications.items() if label == src.id))
        for src in sources
    ]


def audiences(
    payments: list[Payment], subs: list[Subscription], sources: list[RevenueSource], now: int,
    subscriptions_available: bool = True, only: str | None = None, labels: Labels | None = None,
) -> list[Audience]:
    """Every action's audience (or just the action `only`), in library order."""
    labels = labels or Labels()
    facts = Facts(payments, subs, now, labels)
    return [
        audience(action, rule, facts, subscriptions_available)
        for action, rule in library(with_applications(sources, labels))
        if only is None or action.kind == only
    ]
