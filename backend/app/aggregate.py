"""Pure functions turning raw Stripe objects into payments, rankings and timelines. No I/O here.

The unit is a *payment*: one PaymentIntent (every retry of the same payment attaches to it),
enriched with its invoice when it has one (plan description, billing reason, attempt count,
and a snapshot of the customer's email that survives customer deletion).
Money comes from the PaymentIntent's latest charge, which carries the settled amount and refunds.
"""

import calendar
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from app.currency import convert_minor

PERIOD_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12, "all": None}

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


def _description(pi: dict, invoice: dict | None) -> str | None:
    items = ((invoice or {}).get("lines") or {}).get("data", [])
    lines = [d for d in (item.get("description") for item in items) if d]
    if lines:
        text = lines[0] + (f" + {len(lines) - 1} more" if len(lines) > 1 else "")
    else:
        text = pi.get("description")
    if text and len(text) > DESCRIPTION_MAX:
        text = text[: DESCRIPTION_MAX - 1] + "…"
    return text


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
