"""Pure functions turning raw Stripe objects into payments, rankings and timelines. No I/O here.

The unit is a *payment*: one PaymentIntent (every retry of the same payment attaches to it),
enriched with its invoice when it has one (plan description, billing reason, attempt count,
and a snapshot of the customer's email that survives customer deletion).
Money comes from the PaymentIntent's latest charge, which carries the settled amount and refunds.
"""

import calendar
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from app.currency import convert_minor

PERIOD_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12, "all": None}

# Lookback windows for the event lists (cancellations, anniversaries, new subscribers).
WINDOW_DAYS = {"7d": 7}

DESCRIPTION_MAX = 200

# (YYYY-MM-DD, settled currency) -> units of reporting currency per 1 unit of settled currency
Rates = dict[tuple[str, str], float]

Status = Literal["succeeded", "failed", "pending", "canceled"]

PENDING_STATUSES = {"processing", "requires_action", "requires_confirmation", "requires_capture"}


@dataclass(frozen=True)
class Refund:
    created: int
    amount: int  # in the payment's (presentment) currency


@dataclass(frozen=True)
class Payment:
    id: str  # PaymentIntent id
    account_id: str
    created: int
    email: str | None
    status: Status
    description: str | None
    # From the invoice, when there is one.
    billing_reason: str | None  # e.g. subscription_create, subscription_cycle, manual
    attempts: int
    failure_message: str | None
    # In the currency the customer paid.
    currency: str
    amount: int
    amount_refunded: int
    refunds: tuple[Refund, ...]
    # Settled into the account's balance, before fees. None if nothing was collected.
    settled_currency: str | None
    settled_gross: int | None
    settled_net: int | None
    # In the reporting currency. None until converted, or if no FX rate was available.
    gross_reporting: int | None = None
    net_reporting: int | None = None

    @property
    def countable(self) -> bool:
        return self.status == "succeeded"


@dataclass
class CustomerRank:
    email: str
    net_total: int = 0
    payment_count: int = 0
    first_seen: int = 0
    last_seen: int = 0
    accounts: set[str] = field(default_factory=set)


def period_start(period: str, now: datetime | None = None) -> int | None:
    """Unix timestamp for the start of `period`, or None for all time. Calendar months, UTC."""
    months = PERIOD_MONTHS[period]
    if months is None:
        return None
    now = now or datetime.now(UTC)
    year, month = divmod(now.year * 12 + now.month - 1 - months, 12)
    month += 1
    # Clamp e.g. 31 March - 1 month to the last day of February.
    day = min(now.day, calendar.monthrange(year, month)[1])
    return int(now.replace(year=year, month=month, day=day).timestamp())


def window_start(window: str, now: datetime | None = None) -> int:
    """Unix timestamp for the start of a lookback window: "7d", or a calendar-month period."""
    now = now or datetime.now(UTC)
    if window in WINDOW_DAYS:
        return int(now.timestamp()) - WINDOW_DAYS[window] * 86400
    start = period_start(window, now)
    assert start is not None
    return start


def _first(*candidates: str | None) -> str | None:
    for c in candidates:
        if c and c.strip():
            return c.strip().lower()
    return None


def resolve_email(pi: dict, invoice: dict | None) -> str | None:
    """Customer's current email first, then the invoice's snapshot (survives customer deletion),
    then the charge's billing details, then the receipt email."""
    customer = pi.get("customer")
    charge = pi.get("latest_charge") if isinstance(pi.get("latest_charge"), dict) else {}
    return _first(
        customer.get("email") if isinstance(customer, dict) else None,
        (invoice or {}).get("customer_email"),
        (charge.get("billing_details") or {}).get("email"),
        pi.get("receipt_email"),
        charge.get("receipt_email"),
    )


def _status(pi: dict) -> Status | None:
    """None for PaymentIntents the customer never attempted (e.g. an abandoned checkout)."""
    s = pi["status"]
    attempted = bool(pi.get("latest_charge") or pi.get("last_payment_error"))
    if s == "succeeded":
        return "succeeded"
    if s in PENDING_STATUSES:
        return "pending"
    if not attempted:
        return None
    return "canceled" if s == "canceled" else "failed"


def _truncate(text: str | None) -> str | None:
    if text and len(text) > DESCRIPTION_MAX:
        text = text[: DESCRIPTION_MAX - 1] + "…"
    return text


def _description(pi: dict, invoice: dict | None) -> str | None:
    items = ((invoice or {}).get("lines") or {}).get("data", [])
    lines = [d for d in (item.get("description") for item in items) if d]
    if lines:
        return _truncate(lines[0] + (f" + {len(lines) - 1} more" if len(lines) > 1 else ""))
    return _truncate(pi.get("description"))


def _settlement(charge: dict) -> tuple[str | None, int | None, int | None]:
    captured = charge.get("amount_captured") or 0
    if captured <= 0:
        return None, None, None
    net_original = max(captured - (charge.get("amount_refunded") or 0), 0)
    bt = charge.get("balance_transaction")
    if isinstance(bt, dict):
        # The balance transaction holds the captured amount already converted by Stripe
        # into the settlement currency. Refunds settle at their own rate, so applying the
        # charge's rate to the refunded portion is a close approximation, not exact.
        return bt["currency"], bt["amount"], round(bt["amount"] * net_original / captured)
    # Not settled yet (or not expanded): fall back to the presentment currency.
    return charge["currency"], captured, net_original


def normalize_payment(pi: dict, invoice: dict | None, account_id: str) -> Payment | None:
    status = _status(pi)
    if status is None:
        return None
    charge = pi.get("latest_charge") if isinstance(pi.get("latest_charge"), dict) else {}
    collected = status == "succeeded" and bool(charge)
    settled = _settlement(charge) if collected else (None, None, None)
    refunds = tuple(
        Refund(created=r["created"], amount=r["amount"])
        for r in ((charge.get("refunds") or {}).get("data", []) if collected else [])
        if r.get("status") == "succeeded"
    )
    return Payment(
        id=pi["id"],
        account_id=account_id,
        created=pi["created"],
        email=resolve_email(pi, invoice),
        status=status,
        description=_description(pi, invoice),
        billing_reason=(invoice or {}).get("billing_reason"),
        attempts=(invoice or {}).get("attempt_count") or (1 if charge else 0),
        failure_message=None if status == "succeeded" else (pi.get("last_payment_error") or {}).get("message"),
        currency=pi["currency"],
        amount=charge.get("amount_captured") if collected else pi["amount"],
        amount_refunded=(charge.get("amount_refunded") or 0) if collected else 0,
        refunds=refunds,
        settled_currency=settled[0],
        settled_gross=settled[1],
        settled_net=settled[2],
    )


def invoices_by_payment_intent(invoices: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for inv in invoices:
        for p in (inv.get("payments") or {}).get("data", []):
            pi = (p.get("payment") or {}).get("payment_intent")
            if isinstance(pi, str):
                out[pi] = inv
    return out


def rate_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def needed_rates(payments: list[Payment], reporting_currency: str) -> set[tuple[str, str]]:
    return {
        (rate_date(p.created), p.settled_currency)
        for p in payments
        if p.settled_currency and p.settled_currency != reporting_currency
    }


def apply_reporting_currency(
    payments: list[Payment], reporting_currency: str, rates: Rates
) -> list[Payment]:
    out = []
    for p in payments:
        if p.settled_currency is None:
            out.append(replace(p, gross_reporting=0, net_reporting=0))
        elif p.settled_currency == reporting_currency:
            out.append(replace(p, gross_reporting=p.settled_gross, net_reporting=p.settled_net))
        elif (rate := rates.get((rate_date(p.created), p.settled_currency))) is not None:
            out.append(
                replace(
                    p,
                    gross_reporting=convert_minor(p.settled_gross, p.settled_currency, reporting_currency, rate),
                    net_reporting=convert_minor(p.settled_net, p.settled_currency, reporting_currency, rate),
                )
            )
        else:
            out.append(p)  # left unconverted; excluded from totals
    return out


def rank_customers(payments: list[Payment], since: int | None) -> list[CustomerRank]:
    by_email: dict[str, CustomerRank] = {}
    for p in payments:
        if not p.countable or p.email is None or p.net_reporting is None:
            continue
        if since is not None and p.created < since:
            continue
        rank = by_email.setdefault(p.email, CustomerRank(email=p.email))
        rank.net_total += p.net_reporting
        rank.payment_count += 1
        rank.first_seen = min(rank.first_seen or p.created, p.created)
        rank.last_seen = max(rank.last_seen, p.created)
        rank.accounts.add(p.account_id)
    return sorted(by_email.values(), key=lambda r: (-r.net_total, r.email))


def unconverted_count(payments: list[Payment]) -> int:
    return sum(1 for p in payments if p.countable and p.net_reporting is None)


def customer_payments(payments: list[Payment], email: str) -> list[Payment]:
    """A customer's payments, oldest first, attributed exactly as the leaderboard does."""
    return sorted((p for p in payments if p.email == email), key=lambda p: p.created)


def customer_summary(payments: list[Payment]) -> dict:
    paid = [p for p in payments if p.countable and p.net_reporting is not None]
    gross = sum(p.gross_reporting or 0 for p in paid)
    net = sum(p.net_reporting or 0 for p in paid)
    subscription = [p for p in paid if p.billing_reason and p.billing_reason.startswith("subscription")]
    return {
        "net": net,
        "gross": gross,
        "refunded": gross - net,
        "payments": len(paid),
        "failed_payments": sum(1 for p in payments if p.status == "failed"),
        "first_paid": paid[0].created if paid else None,
        "last_paid": paid[-1].created if paid else None,
        "current_plan": subscription[-1].description if subscription else None,
    }


EventKind = Literal[
    "subscribed", "renewed", "subscription_changed", "purchased",
    "payment_failed", "payment_pending", "payment_canceled", "refunded",
]

_SUCCESS_KIND: dict[str | None, EventKind] = {
    "subscription_create": "subscribed",
    "subscription_cycle": "renewed",
    "subscription_update": "subscription_changed",
}


@dataclass(frozen=True)
class TimelineEvent:
    kind: EventKind
    date: int
    account_id: str
    description: str | None
    currency: str
    amount: int
    amount_reporting: int | None
    attempts: int
    failure_message: str | None


def timeline(payments: list[Payment]) -> list[TimelineEvent]:
    """One event per payment plus one per refund, oldest first."""
    events: list[TimelineEvent] = []
    for p in payments:
        kind: EventKind
        if p.status == "succeeded":
            kind = _SUCCESS_KIND.get(p.billing_reason, "purchased")
        else:
            kind = {"failed": "payment_failed", "pending": "payment_pending", "canceled": "payment_canceled"}[p.status]
        base = dict(account_id=p.account_id, description=p.description, currency=p.currency)
        events.append(TimelineEvent(
            kind=kind, date=p.created, amount=p.amount,
            amount_reporting=p.gross_reporting if p.countable else None,
            attempts=p.attempts, failure_message=p.failure_message, **base,
        ))
        for r in p.refunds:
            events.append(TimelineEvent(
                kind="refunded", date=r.created, amount=r.amount, amount_reporting=None,
                attempts=0, failure_message=None, **base,
            ))
    return sorted(events, key=lambda e: e.date)


# ---- Subscriptions: cancellations, new subscribers, anniversaries ----

# Statuses where the customer is still subscribed (past_due: Stripe is still retrying the payment).
CURRENT_STATUSES = {"active", "trialing", "past_due"}
# The first payment never went through, so the subscription never really started.
NEVER_STARTED = {"incomplete", "incomplete_expired"}


@dataclass(frozen=True)
class Subscription:
    id: str
    account_id: str
    email: str | None
    status: str
    plan: str | None
    started: int
    canceled_at: int | None  # when the cancellation was made (it may take effect later)
    ends_at: int | None  # when it ended, or is scheduled to end
    cancel_reason: str | None  # cancellation_requested, payment_failed or payment_disputed
    cancel_feedback: str | None  # the customer's chosen reason, e.g. too_expensive

    @property
    def current(self) -> bool:
        return self.status in CURRENT_STATUSES


def _is_proration(line: dict) -> bool:
    # Older API versions flag the line itself; newer ones nest it under the line's parent.
    details = (line.get("parent") or {}).get("subscription_item_details") or {}
    return bool(line.get("proration") or details.get("proration"))


# Stripe's wording for the charged line of a plan change, e.g. "Remaining time on Annual after 30 Sep 2026".
_REMAINING_TIME = re.compile(r"^Remaining time on (?:\d+ × )?(.+?) after .+$")


def _plan(sub: dict, invoice: dict) -> str | None:
    """The latest invoice's plan line. A plan change's invoice holds only proration lines
    ("Unused time on Monthly …", "Remaining time on Annual …"), so then the price's nickname
    is used, else the charged proration line, which names the new plan."""
    lines = [line for line in (invoice.get("lines") or {}).get("data", []) if line.get("description")]
    if regular := [line for line in lines if not _is_proration(line)]:
        return _truncate(regular[0]["description"])
    items = (sub.get("items") or {}).get("data", [])
    if nickname := (items[0].get("price") or {}).get("nickname") if items else None:
        return _truncate(nickname)
    if not lines:
        return None
    text = ([line for line in lines if (line.get("amount") or 0) > 0] or lines)[-1]["description"]
    m = _REMAINING_TIME.match(text)
    return _truncate(m.group(1) if m else text)


def normalize_subscription(sub: dict, account_id: str) -> Subscription:
    customer = sub.get("customer")
    invoice = sub.get("latest_invoice") if isinstance(sub.get("latest_invoice"), dict) else {}
    details = sub.get("cancellation_details") or {}
    return Subscription(
        id=sub["id"],
        account_id=account_id,
        # The invoice's copy of the email survives the customer being deleted.
        email=_first(customer.get("email") if isinstance(customer, dict) else None, invoice.get("customer_email")),
        status=sub["status"],
        plan=_plan(sub, invoice),
        started=sub.get("start_date") or sub["created"],
        canceled_at=sub.get("canceled_at"),
        ends_at=sub.get("ended_at") or sub.get("cancel_at"),
        cancel_reason=details.get("reason"),
        cancel_feedback=details.get("feedback"),
    )


def _by_email(subs: list[Subscription]) -> dict[str, list[Subscription]]:
    out: dict[str, list[Subscription]] = {}
    for s in subs:
        if s.email is not None:
            out.setdefault(s.email, []).append(s)
    return out


@dataclass(frozen=True)
class Cancellation:
    sub: Subscription
    resubscribed: bool  # has another subscription that's current and not itself canceling


def cancellations(subs: list[Subscription], since: int) -> list[Cancellation]:
    """Subscriptions canceled at or after `since`, most recent first. Includes cancellations
    scheduled for the end of the billing period, which are still active until `ends_at`."""
    by_email = _by_email(subs)
    out = [
        Cancellation(
            sub=s,
            resubscribed=any(o.id != s.id and o.current and o.canceled_at is None for o in by_email[s.email]),
        )
        for s in subs
        if s.email is not None and s.canceled_at is not None and s.canceled_at >= since
        and s.status not in NEVER_STARTED
    ]
    return sorted(out, key=lambda c: (-(c.sub.canceled_at or 0), c.sub.email))


@dataclass(frozen=True)
class NewSubscription:
    sub: Subscription
    returning: bool  # had an earlier subscription that ended before this one started


def new_subscriptions(subs: list[Subscription], since: int) -> list[NewSubscription]:
    """Subscriptions started at or after `since`, most recent first."""
    by_email = _by_email(subs)
    out = [
        NewSubscription(
            sub=s,
            returning=any(o.id != s.id and o.ends_at is not None and o.ends_at <= s.started for o in by_email[s.email]),
        )
        for s in subs
        if s.email is not None and s.started >= since and s.status not in NEVER_STARTED
    ]
    return sorted(out, key=lambda n: (-n.sub.started, n.sub.email))


def _add_years(d: datetime, years: int) -> datetime:
    # A 29 February start has its anniversary on 28 February in non-leap years.
    day = min(d.day, calendar.monthrange(d.year + years, d.month)[1])
    return d.replace(year=d.year + years, day=day)


def latest_anniversary(first: int, now: int) -> tuple[int, int] | None:
    """(years, date) of the most recent anniversary of `first` on or before `now`; None before the first."""
    start, current = datetime.fromtimestamp(first, UTC), datetime.fromtimestamp(now, UTC)
    years = current.year - start.year
    if _add_years(start, years) > current:
        years -= 1
    if years < 1:
        return None
    return years, int(_add_years(start, years).timestamp())


@dataclass(frozen=True)
class Anniversary:
    customer: CustomerRank
    years: int
    date: int
    subscribed: bool  # has a current subscription


def anniversaries(
    ranks: list[CustomerRank], subs: list[Subscription], since: int, now: int
) -> list[Anniversary]:
    """Customers whose first successful payment had an anniversary at or after `since`, most recent first."""
    subscribed = {s.email for s in subs if s.current}
    out = []
    for r in ranks:
        if (a := latest_anniversary(r.first_seen, now)) and a[1] >= since:
            out.append(Anniversary(customer=r, years=a[0], date=a[1], subscribed=r.email in subscribed))
    return sorted(out, key=lambda a: (-a.date, a.customer.email))
