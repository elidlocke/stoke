"""API response models: the allowlist of everything that leaves the backend.

Raw Stripe objects are never serialized. In particular, never add card/payment-method
details, addresses, phone numbers, metadata, receipt URLs or Stripe error bodies here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Period = Literal["1m", "3m", "6m", "12m", "all"]
# Lookback window for the event lists: past week, month or 3 months.
Window = Literal["7d", "1m", "3m"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountOut(_Out):
    id: str
    display_name: str
    settlement_currency: str
    # platform: our Connect platform; connected: read via the platform; own_key: the account's own key
    access: Literal["platform", "connected", "own_key"]


class AccountsResponse(_Out):
    reporting_currency: str
    accounts: list[AccountOut]


class LeaderboardEntry(_Out):
    rank: int
    email: str
    customer_id: str  # opaque id for the profile URL (see app/customer_id.py)
    net_total: int  # minor units of reporting_currency
    payment_count: int
    last_seen: int  # unix seconds
    accounts: list[str]  # account ids


class LeaderboardResponse(_Out):
    period: Period
    since: int | None
    reporting_currency: str
    customers: list[LeaderboardEntry]
    # Payments whose settlement currency couldn't be converted (no FX rate); excluded from totals.
    unconverted_count: int


EventKind = Literal[
    "subscribed", "renewed", "subscription_changed", "purchased",
    "payment_failed", "payment_pending", "payment_canceled", "refunded",
]


class TimelineEventOut(_Out):
    kind: EventKind
    date: int  # unix seconds
    account_id: str
    description: str | None  # plan or invoice line, e.g. "1 × Monthly (at $8.00 / month)"
    currency: str  # currency the customer paid in
    amount: int  # payment amount, or refund amount for "refunded"
    # The payment in the reporting currency, before refunds (refunds are their own events).
    # Only set for successful payments.
    amount_reporting: int | None
    attempts: int  # payment attempts (retries of the same payment are one event)
    failure_message: str | None  # Stripe's customer-facing decline reason, e.g. "Your card was declined."


class CustomerSummary(_Out):
    net: int
    gross: int
    refunded: int
    payments: int  # successful payments
    failed_payments: int
    first_paid: int | None
    last_paid: int | None
    current_plan: str | None  # description of the most recent subscription payment


class CustomerProfileResponse(_Out):
    email: str
    customer_id: str  # opaque id for the profile URL (see app/customer_id.py)
    reporting_currency: str
    summary: CustomerSummary
    timeline: list[TimelineEventOut]  # oldest first


class CancellationEntry(_Out):
    email: str
    customer_id: str  # opaque id for the profile URL (see app/customer_id.py)
    account_id: str
    plan: str | None
    started: int  # unix seconds
    canceled_at: int  # when the cancellation was made
    ends_at: int | None  # when access ended, or will end
    ended: bool  # False: canceled at period end, still active until ends_at
    # Stripe's cancellation_details: reason is cancellation_requested, payment_failed or payment_disputed;
    # feedback is the customer's chosen reason, e.g. too_expensive. The free-text comment is never returned.
    reason: str | None
    feedback: str | None
    lifetime_value: int  # net paid across all time, minor units of reporting_currency
    resubscribed: bool  # has another current subscription


class CancellationsResponse(_Out):
    window: Window
    since: int
    reporting_currency: str
    customers: list[CancellationEntry]  # most recent cancellation first


class AnniversaryEntry(_Out):
    email: str
    customer_id: str  # opaque id for the profile URL (see app/customer_id.py)
    years: int  # 1 for the first anniversary, 2 for the second, ...
    anniversary: int  # unix seconds
    first_paid: int
    last_paid: int
    lifetime_value: int  # minor units of reporting_currency
    payment_count: int
    subscribed: bool  # has a current subscription
    accounts: list[str]


class AnniversariesResponse(_Out):
    window: Window
    since: int
    reporting_currency: str
    customers: list[AnniversaryEntry]  # most recent anniversary first


class NewSubscriberEntry(_Out):
    email: str
    customer_id: str  # opaque id for the profile URL (see app/customer_id.py)
    account_id: str
    plan: str | None
    started: int  # unix seconds
    status: str  # Stripe subscription status: active, trialing, past_due, canceled, ...
    returning: bool  # had an earlier subscription that ended before this one started


class NewSubscribersResponse(_Out):
    window: Window
    since: int
    customers: list[NewSubscriberEntry]  # most recent first
