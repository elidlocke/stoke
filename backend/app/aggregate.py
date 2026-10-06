"""Pure functions turning raw Stripe objects into payments, rankings and timelines. No I/O here.

The unit is a *payment*: one PaymentIntent (every retry of the same payment attaches to it),
enriched with its invoice when it has one (plan description, billing reason, attempt count,
and a snapshot of the customer's email that survives customer deletion).
Money comes from the PaymentIntent's latest charge, which carries the settled amount and refunds.
"""

import bisect
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
    pending: bool = False  # not yet confirmed; counted anyway, since Stripe has already taken it


@dataclass(frozen=True)
class DisputeMovement:
    """Money Stripe moved for a dispute, from the dispute's balance transactions (settled currency)."""
    created: int
    amount: int  # negative: withdrawn from the balance; positive: returned after a win
    fee: int  # the dispute fee charged (positive), or returned (negative)


@dataclass(frozen=True)
class Dispute:
    created: int
    # warning_needs_response / warning_under_review / warning_closed: an inquiry, nothing withdrawn.
    # needs_response / under_review: funds withdrawn while the dispute is open. won / lost.
    status: str
    reason: str | None  # e.g. fraudulent, product_not_received
    amount: int  # disputed amount, in the payment's (presentment) currency
    respond_by: int | None  # evidence deadline
    movements: tuple[DisputeMovement, ...]


@dataclass(frozen=True)
class Fee:
    # application_fee is the platform's cut (e.g. Substack's 10%); stripe_fee is Stripe's processing
    # fee. Stripe also uses tax and payment_method_passthrough_fee.
    type: str
    description: str | None  # Stripe's label, e.g. "Substack application fee"
    amount: int


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
    # Settled into the account's balance. None if nothing was collected.
    settled_currency: str | None
    settled_gross: int | None  # what the customer paid
    settled_net: int | None  # minus refunds, before fees
    settled_fees: tuple[Fee, ...] = ()  # deducted when the payment was made; not returned on refund
    dispute: Dispute | None = None
    # In the reporting currency. None until converted, or if no FX rate was available.
    gross_reporting: int | None = None
    net_reporting: int | None = None
    fees_reporting: tuple[Fee, ...] | None = None
    dispute_reporting: tuple[DisputeMovement, ...] | None = None
    # What stays in the balance: minus refunds, fees, and money taken back by disputes. Like
    # Stripe's balance, an open dispute counts as lost until it's won.
    take_home_reporting: int | None = None

    @property
    def countable(self) -> bool:
        return self.status == "succeeded"


@dataclass
class CustomerRank:
    email: str
    take_home: int = 0
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


# Stripe's invoice line for a subscription: "1 × <product name> (at <price> / <interval>)".
_PLAN_LINE = re.compile(r"^(?:(\d+) × )?(.+?) \(at .+ / (.+)\)$")
# Product names that are really a price, e.g. Substack's "$8 a month". They can disagree with the
# actual price (here, CA$12.00 a month), so they're dropped in favour of the billing interval.
_PRICE_LIKE = re.compile(r"[$€£¥₹]|\d+(?:[.,]\d+)?\s*(?:a|per|/)\s*(?:day|week|month|year)", re.IGNORECASE)
_INTERVALS = {
    "day": ("Daily", ("day", "daily")),
    "week": ("Weekly", ("week",)),
    "month": ("Monthly", ("month",)),
    "year": ("Yearly", ("year", "annual")),
}


def plan_label(line: str) -> str:
    """A readable plan name from an invoice line, without the price (shown separately):
    "1 × $8 a month (at $12.00 / month)" -> "Monthly plan",
    "1 × Founding member (at $150.00 / year)" -> "Founding member · yearly"."""
    m = _PLAN_LINE.match(line)
    if not m:
        return line
    quantity, name, interval = m.groups()
    unit = interval.split()[-1].removesuffix("s")  # "month", or "months" in "every 3 months"
    adjective, words = _INTERVALS.get(unit, (None, ()))
    every = interval.startswith("every ")
    if _PRICE_LIKE.search(name):
        label = f"Plan billed {interval}" if every or not adjective else f"{adjective} plan"
    elif every:
        label = f"{name} · {interval}"
    elif adjective and not any(w in name.lower() for w in words):
        label = f"{name} · {adjective.lower()}"
    else:
        label = name
    return f"{quantity} × {label}" if quantity and quantity != "1" else label


def _description(pi: dict, invoice: dict | None) -> str | None:
    items = ((invoice or {}).get("lines") or {}).get("data", [])
    lines = [d for d in (item.get("description") for item in items) if d]
    if lines:
        return _truncate(plan_label(lines[0]) + (f" + {len(lines) - 1} more" if len(lines) > 1 else ""))
    return _truncate(pi.get("description"))


def _settlement(charge: dict) -> tuple[str | None, int | None, int | None, tuple[Fee, ...]]:
    captured = charge.get("amount_captured") or 0
    if captured <= 0:
        return None, None, None, ()
    net_original = max(captured - (charge.get("amount_refunded") or 0), 0)
    bt = charge.get("balance_transaction")
    if isinstance(bt, dict):
        # The balance transaction holds the captured amount already converted by Stripe
        # into the settlement currency. Refunds settle at their own rate, so applying the
        # charge's rate to the refunded portion is a close approximation, not exact.
        fees = tuple(
            Fee(type=f["type"], description=_truncate(f.get("description")), amount=f["amount"])
            for f in bt.get("fee_details") or []
        )
        return bt["currency"], bt["amount"], round(bt["amount"] * net_original / captured), fees
    # Not settled yet (or not expanded): fall back to the presentment currency. Fees aren't known yet.
    return charge["currency"], captured, net_original, ()


def normalize_payment(pi: dict, invoice: dict | None, account_id: str) -> Payment | None:
    status = _status(pi)
    if status is None:
        return None
    charge = pi.get("latest_charge") if isinstance(pi.get("latest_charge"), dict) else {}
    collected = status == "succeeded" and bool(charge)
    settled = _settlement(charge) if collected else (None, None, None, ())
    refunds = tuple(
        Refund(created=r["created"], amount=r["amount"], pending=r.get("status") == "pending")
        for r in ((charge.get("refunds") or {}).get("data", []) if collected else [])
        if r.get("status") in ("succeeded", "pending")  # Stripe's amount_refunded counts both
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
        settled_fees=settled[3],
        dispute=_dispute(charge) if collected else None,
    )


def _dispute(charge: dict) -> Dispute | None:
    """Only amounts, dates and status: the dispute's evidence holds customer details and never leaves here."""
    d = charge.get("dispute")
    if not isinstance(d, dict):
        return None
    return Dispute(
        created=d["created"],
        status=d["status"],
        reason=d.get("reason"),
        amount=d["amount"],
        respond_by=(d.get("evidence_details") or {}).get("due_by"),
        movements=tuple(
            DisputeMovement(created=bt["created"], amount=bt["amount"], fee=bt.get("fee") or 0)
            for bt in d.get("balance_transactions") or []
        ),
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
            out.append(replace(
                p, gross_reporting=0, net_reporting=0, fees_reporting=(), dispute_reporting=(), take_home_reporting=0,
            ))
            continue
        if p.settled_currency == reporting_currency:
            rate = 1.0
        elif (rate := rates.get((rate_date(p.created), p.settled_currency))) is None:
            out.append(p)  # left unconverted; excluded from totals
            continue

        def conv(amount: int, rate: float = rate, currency: str = p.settled_currency) -> int:
            return amount if currency == reporting_currency else convert_minor(amount, currency, reporting_currency, rate)

        gross = conv(p.settled_gross)
        # Refunds as a share of the converted gross, so the timeline's per-refund amounts
        # (see refund_shares) add up to exactly this.
        net = gross - (round(gross * p.amount_refunded / p.amount) if p.amount else 0)
        fees = tuple(replace(f, amount=conv(f.amount)) for f in p.settled_fees)
        # Dispute movements are dated later, but converting at the payment's rate keeps a
        # won dispute's withdrawal and return cancelling out exactly.
        dispute = tuple(
            replace(m, amount=conv(m.amount), fee=conv(m.fee)) for m in (p.dispute.movements if p.dispute else ())
        )
        out.append(replace(
            p,
            gross_reporting=gross,
            net_reporting=net,
            fees_reporting=fees,
            dispute_reporting=dispute,
            # Converted parts, so a breakdown always adds up exactly.
            take_home_reporting=net - sum(f.amount for f in fees) + sum(m.amount - m.fee for m in dispute),
        ))
    return out


def rank_customers(payments: list[Payment], since: int | None) -> list[CustomerRank]:
    by_email: dict[str, CustomerRank] = {}
    for p in payments:
        if not p.countable or p.email is None or p.take_home_reporting is None:
            continue
        if since is not None and p.created < since:
            continue
        rank = by_email.setdefault(p.email, CustomerRank(email=p.email))
        rank.take_home += p.take_home_reporting
        rank.payment_count += 1
        rank.first_seen = min(rank.first_seen or p.created, p.created)
        rank.last_seen = max(rank.last_seen, p.created)
        rank.accounts.add(p.account_id)
    return sorted(by_email.values(), key=lambda r: (-r.take_home, r.email))


def unconverted_count(payments: list[Payment]) -> int:
    return sum(1 for p in payments if p.countable and p.take_home_reporting is None)


def customer_payments(payments: list[Payment], email: str) -> list[Payment]:
    """A customer's payments, oldest first, attributed exactly as the leaderboard does."""
    return sorted((p for p in payments if p.email == email), key=lambda p: p.created)


def customer_summary(payments: list[Payment]) -> dict:
    paid = [p for p in payments if p.countable and p.take_home_reporting is not None]
    gross = sum(p.gross_reporting or 0 for p in paid)
    net = sum(p.net_reporting or 0 for p in paid)
    fees = sum(f.amount for p in paid for f in p.fees_reporting or ())
    # What disputes took back, net of anything returned after a win, including dispute fees.
    disputed = -sum(m.amount - m.fee for p in paid for m in p.dispute_reporting or ())
    subscription = [p for p in paid if p.billing_reason and p.billing_reason.startswith("subscription")]
    return {
        "take_home": net - fees - disputed,
        "gross": gross,
        "refunded": gross - net,
        "fees": fees,
        "disputed": disputed,
        "open_disputes": sum(1 for p in paid if p.dispute and p.dispute.status in OPEN_DISPUTE_STATUSES),
        "payments": len(paid),
        "failed_payments": sum(1 for p in payments if p.status == "failed"),
        "first_paid": paid[0].created if paid else None,
        "last_paid": paid[-1].created if paid else None,
        "current_plan": subscription[-1].description if subscription else None,
    }


EventKind = Literal[
    "subscribed", "renewed", "subscription_changed", "purchased",
    "payment_failed", "payment_pending", "payment_canceled", "refunded",
    "disputed", "dispute_won", "dispute_inquiry",
]

# Disputes still awaiting the creator's response or the bank's decision.
OPEN_DISPUTE_STATUSES = {"needs_response", "under_review", "warning_needs_response", "warning_under_review"}

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
    amount: int  # the payment, or the refund or dispute amount, in the customer's currency
    # In the reporting currency: the payment (before refunds), refund, or dispute amount.
    amount_reporting: int | None
    attempts: int
    failure_message: str | None
    # Fees deducted by this event: the payment's fees, or a dispute fee.
    fees: tuple[Fee, ...] = ()
    # What the payment leaves the creator before and after this event, in the reporting currency.
    # A payment's take_home is gross minus fees; each refund or dispute event then moves it.
    take_home_before: int | None = None
    take_home: int | None = None
    fees_not_returned: int | None = None  # refunds: the payment's fees, which Stripe keeps
    pending: bool = False  # refunds not yet confirmed
    dispute_status: str | None = None
    dispute_reason: str | None = None
    respond_by: int | None = None


def refund_shares(p: Payment) -> list[int]:
    """Each refund in the reporting currency, as a share of the converted payment. Rounded
    cumulatively, so they sum to exactly what the totals subtract."""
    if p.gross_reporting is None or not p.amount:
        return [0] * len(p.refunds)
    shares, done, cumulative = [], 0, 0
    for r in sorted(p.refunds, key=lambda r: r.created):
        cumulative += r.amount
        total = round(p.gross_reporting * cumulative / p.amount)
        shares.append(total - done)
        done = total
    return shares


def timeline(payments: list[Payment]) -> list[TimelineEvent]:
    """One event per payment, plus one per refund and per dispute step, oldest first."""
    events: list[TimelineEvent] = []
    for p in payments:
        kind: EventKind
        if p.status == "succeeded":
            kind = _SUCCESS_KIND.get(p.billing_reason, "purchased")
        else:
            kind = {"failed": "payment_failed", "pending": "payment_pending", "canceled": "payment_canceled"}[p.status]
        base = dict(account_id=p.account_id, description=p.description, currency=p.currency)
        paid = p.countable and p.gross_reporting is not None and p.fees_reporting is not None
        fees = p.fees_reporting if paid and p.fees_reporting else ()
        fee_total = sum(f.amount for f in fees)
        kept = p.gross_reporting - fee_total if paid else None
        events.append(TimelineEvent(
            kind=kind, date=p.created, amount=p.amount,
            amount_reporting=p.gross_reporting if p.countable else None,
            attempts=p.attempts, failure_message=p.failure_message, fees=fees, take_home=kept, **base,
        ))

        # What happened to the payment afterwards, in date order, each moving what it leaves.
        later: list[tuple[int, dict]] = []
        for r, share in zip(sorted(p.refunds, key=lambda r: r.created), refund_shares(p)):
            later.append((r.created, dict(
                kind="refunded", amount=r.amount, amount_reporting=share if paid else None,
                delta=-share, fees_not_returned=fee_total if paid else None, pending=r.pending,
            )))
        if d := p.dispute:
            info = dict(dispute_status=d.status, dispute_reason=d.reason, respond_by=d.respond_by)
            movements = zip(sorted(d.movements, key=lambda m: m.created), p.dispute_reporting or [None] * len(d.movements))
            for m, moved in movements:
                if m.amount < 0 or (m.amount == 0 and m.fee > 0):
                    later.append((m.created, dict(
                        kind="disputed", amount=d.amount,
                        amount_reporting=-moved.amount if moved else None,
                        fees=(Fee("dispute_fee", "Dispute fee", moved.fee),) if moved and moved.fee else (),
                        delta=moved.amount - moved.fee if moved else 0, **info,
                    )))
                else:
                    later.append((m.created, dict(
                        kind="dispute_won", amount=d.amount,
                        amount_reporting=moved.amount if moved else None,
                        fees=(Fee("dispute_fee", "Dispute fee returned", moved.fee),) if moved and moved.fee else (),
                        delta=moved.amount - moved.fee if moved else 0, **info,
                    )))
            if not d.movements:  # an inquiry: no money has moved
                later.append((d.created, dict(kind="dispute_inquiry", amount=d.amount, amount_reporting=None, delta=0, **info)))

        for date, e in sorted(later, key=lambda x: x[0]):
            delta = e.pop("delta")
            before = kept
            if kept is not None and paid:
                kept += delta
            events.append(TimelineEvent(
                date=date, attempts=0, failure_message=None,
                take_home_before=before if paid else None, take_home=kept if paid else None, **e, **base,
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
    # From the latest invoice: while a payment is failing, what's owed and when Stripe retries next.
    invoice_created: int | None = None
    invoice_amount_due: int | None = None  # in invoice_currency (the customer's)
    invoice_currency: str | None = None
    invoice_attempts: int | None = None
    next_retry: int | None = None  # None once Stripe has stopped retrying

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
        return _truncate(plan_label(regular[0]["description"]))
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
        invoice_created=invoice.get("created"),
        invoice_amount_due=invoice.get("amount_due"),
        invoice_currency=invoice.get("currency"),
        invoice_attempts=invoice.get("attempt_count"),
        next_retry=invoice.get("next_payment_attempt"),
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
    # The customer's subscription now, if they still have one that isn't itself canceling.
    current: Subscription | None

    @property
    def resubscribed(self) -> bool:
        """Came back: the current subscription started after this one was canceled
        (rather than running alongside it, e.g. a second plan or a second customer record)."""
        return self.current is not None and self.current.started >= (self.sub.canceled_at or 0)


def cancellations(subs: list[Subscription], since: int) -> list[Cancellation]:
    """Subscriptions canceled at or after `since`, most recent first. Includes cancellations
    scheduled for the end of the billing period, which are still active until `ends_at`."""
    by_email = _by_email(subs)
    def current(s: Subscription) -> Subscription | None:
        others = [o for o in by_email[s.email] if o.id != s.id and o.current and o.canceled_at is None]
        return max(others, key=lambda o: o.started, default=None)

    out = [
        Cancellation(sub=s, current=current(s))
        for s in subs
        if s.email is not None and s.canceled_at is not None and s.canceled_at >= since
        and s.status not in NEVER_STARTED
    ]
    return sorted(out, key=lambda c: (-(c.sub.canceled_at or 0), c.sub.email))


@dataclass(frozen=True)
class NewCustomer:
    email: str
    first_seen: int  # their first successful payment or subscription start, whichever came first
    account_id: str  # where that happened
    # "subscription": started by subscribing (including a trial with nothing charged yet);
    # "purchase": started with a one-off payment, e.g. a coaching session or a tip.
    started_with: Literal["subscription", "purchase"]
    description: str | None  # the plan, or what the one-off payment was for
    subscription_status: str | None  # their most recent subscription's status, if they have one
    take_home: int  # so far, in the reporting currency


def new_customers(payments: list[Payment], subs: list[Subscription], since: int) -> list[NewCustomer]:
    """Customers whose very first successful payment or subscription was at or after `since`,
    most recent first. Someone returning after a cancellation, or subscribing after an earlier
    one-off purchase, isn't new."""
    paid: dict[str, list[Payment]] = {}
    for p in sorted(payments, key=lambda p: p.created):
        if p.countable and p.email is not None:
            paid.setdefault(p.email, []).append(p)
    started = _by_email([s for s in subs if s.status not in NEVER_STARTED])
    take_home = {r.email: r.take_home for r in rank_customers(payments, None)}

    out = []
    for email in paid.keys() | started.keys():
        first_payment = paid[email][0] if email in paid else None
        first_sub = min(started.get(email, []), key=lambda s: s.started, default=None)
        latest_sub = max(started.get(email, []), key=lambda s: s.started, default=None)
        # A subscription starts a moment before its first payment, so a payment that comes first
        # (and isn't itself a subscription payment) was a one-off purchase.
        is_purchase = first_payment is not None and (first_sub is None or first_payment.created < first_sub.started) and not (
            first_payment.billing_reason or ""
        ).startswith("subscription")
        if is_purchase:
            assert first_payment is not None
            first_seen, account_id, description = first_payment.created, first_payment.account_id, first_payment.description
        elif first_sub is not None:
            first_seen, account_id, description = first_sub.started, first_sub.account_id, first_sub.plan
            if first_payment is not None:
                first_seen = min(first_seen, first_payment.created)
        else:  # a subscription payment whose subscription isn't listed (e.g. its key can't read them)
            assert first_payment is not None
            first_seen, account_id, description = first_payment.created, first_payment.account_id, first_payment.description
        if first_seen >= since:
            out.append(NewCustomer(
                email=email, first_seen=first_seen, account_id=account_id,
                started_with="purchase" if is_purchase else "subscription", description=description,
                subscription_status=latest_sub.status if latest_sub else None, take_home=take_home.get(email, 0),
            ))
    return sorted(out, key=lambda n: (-n.first_seen, n.email))


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


# ---- At risk: customers who are slipping away but can still be reached ----

RiskKind = Literal["payment_failing", "retries_exhausted", "canceling", "lapsed", "dispute"]

# Stripe has stopped retrying an unpaid subscription; past this, it's an old loss rather than a lead.
UNPAID_LOOKBACK = 90 * 86400
# A subscription canceled by a failed payment is worth a note for this long afterwards.
LAPSED_LOOKBACK = 30 * 86400
# Disputes still waiting on the creator: evidence for a dispute, or a reply to an inquiry.
DISPUTE_NEEDS_RESPONSE = {"needs_response", "warning_needs_response"}


@dataclass(frozen=True)
class AtRisk:
    kind: RiskKind
    email: str
    account_id: str
    plan: str | None  # the subscription's plan, or the disputed payment's description
    since: int  # when it started: the failing invoice, the cancellation, or the dispute
    # The date to act by: Stripe's next retry, when access ends, or the evidence deadline.
    deadline: int | None
    # Owed by a failing payment, or disputed, in the customer's currency.
    amount: int | None = None
    currency: str | None = None
    attempts: int | None = None
    failure_message: str | None = None  # Stripe's decline reason for the latest failed attempt
    feedback: str | None = None  # canceling: the customer's chosen reason, e.g. too_expensive
    dispute_reason: str | None = None


def at_risk(payments: list[Payment], subs: list[Subscription], now: int) -> list[AtRisk]:
    """Customers to reach out to now, most urgent deadline first; those without a deadline last,
    most recent first. A customer with another subscription that isn't ending is staying, so a
    second plan canceling or lapsing doesn't put them at risk."""
    by_email = _by_email(subs)

    def staying(s: Subscription) -> bool:
        return any(o.id != s.id and o.current and o.canceled_at is None for o in by_email[s.email])

    failures: dict[tuple[str, str], Payment] = {}
    for p in sorted(payments, key=lambda p: p.created):
        if p.status == "failed" and p.email is not None:
            failures[(p.email, p.account_id)] = p

    out: list[AtRisk] = []
    for s in subs:
        if s.email is None:
            continue
        failing = s.status == "past_due" or (
            s.status == "unpaid" and (s.invoice_created or 0) >= now - UNPAID_LOOKBACK
        )
        if failing:
            last_failure = failures.get((s.email, s.account_id))
            out.append(AtRisk(
                kind="payment_failing" if s.status == "past_due" else "retries_exhausted",
                email=s.email, account_id=s.account_id, plan=s.plan,
                since=s.invoice_created or s.started,
                deadline=s.next_retry if s.status == "past_due" else None,
                amount=s.invoice_amount_due, currency=s.invoice_currency, attempts=s.invoice_attempts,
                failure_message=last_failure.failure_message if last_failure else None,
            ))
        if s.current and s.canceled_at is not None and (s.ends_at or now + 1) > now and not staying(s):
            out.append(AtRisk(
                kind="canceling", email=s.email, account_id=s.account_id, plan=s.plan,
                since=s.canceled_at, deadline=s.ends_at, feedback=s.cancel_feedback,
            ))
        if (
            s.status == "canceled" and s.cancel_reason == "payment_failed"
            and (s.canceled_at or 0) >= now - LAPSED_LOOKBACK and not staying(s)
        ):
            out.append(AtRisk(
                kind="lapsed", email=s.email, account_id=s.account_id, plan=s.plan,
                since=s.canceled_at or s.started, deadline=None,
            ))

    for p in payments:
        d = p.dispute
        if d is not None and p.email is not None and d.status in DISPUTE_NEEDS_RESPONSE:
            out.append(AtRisk(
                kind="dispute", email=p.email, account_id=p.account_id, plan=p.description,
                since=d.created, deadline=d.respond_by, amount=d.amount, currency=p.currency,
                dispute_reason=d.reason,
            ))

    return sorted(out, key=lambda r: (r.deadline is None, r.deadline or 0, -r.since, r.email))


# ---- Trends: month by month ----

TREND_MONTHS = 12


def month_starts(count: int, now: datetime) -> list[int]:
    """The starts of the last `count` calendar months (UTC), oldest first; the last is the current month."""
    out = []
    for back in range(count - 1, -1, -1):
        year, month = divmod(now.year * 12 + now.month - 1 - back, 12)
        out.append(int(datetime(year, month + 1, 1, tzinfo=UTC).timestamp()))
    return out


@dataclass
class TrendMonth:
    start: int  # unix seconds: the first moment of the month, UTC
    partial: bool  # the current month, still in progress
    new_customers: int = 0  # first successful payment or subscription this month
    churned: int = 0  # subscribers whose access ended this month, with nothing else still running
    take_home: int = 0  # from payments made this month, after their refunds, fees and disputes


def churn_dates(subs: list[Subscription]) -> list[tuple[str, int]]:
    """(email, when) for every subscription that ended while the customer had no other subscription
    running. A plan change or a second plan isn't churn; leaving and coming back later is."""
    by_email = _by_email([s for s in subs if s.status not in NEVER_STARTED])
    out = []
    for email, own in by_email.items():
        for s in own:
            if s.status != "canceled" or s.ends_at is None:
                continue
            end = s.ends_at
            covered = any(
                o.id != s.id and o.started <= end and (o.status != "canceled" or (o.ends_at or 0) > end)
                for o in own
            )
            if not covered:
                out.append((email, end))
    return out


def trends(payments: list[Payment], subs: list[Subscription], now: datetime, months: int = TREND_MONTHS) -> list[TrendMonth]:
    """New customers, churned subscribers and take-home for each of the last `months` calendar months.
    Refunds and disputes count against the month of the payment, as on the leaderboard."""
    starts = month_starts(months, now)
    out = [TrendMonth(start=s, partial=i == months - 1) for i, s in enumerate(starts)]

    def bucket(ts: int) -> TrendMonth | None:
        i = bisect.bisect_right(starts, ts) - 1
        return out[i] if 0 <= i and ts <= now.timestamp() else None

    for n in new_customers(payments, subs, starts[0]):
        if m := bucket(n.first_seen):
            m.new_customers += 1
    for _, end in churn_dates(subs):
        if m := bucket(end):
            m.churned += 1
    for p in payments:
        if p.countable and p.take_home_reporting is not None and (m := bucket(p.created)):
            m.take_home += p.take_home_reporting
    return out
