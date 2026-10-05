"""API response models: the allowlist of everything that leaves the backend.

Raw Stripe objects are never serialized. In particular, never add card/payment-method
details, addresses, phone numbers, metadata, receipt URLs or Stripe error bodies here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Period = Literal["1m", "3m", "6m", "12m", "all"]


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
    reporting_currency: str
    summary: CustomerSummary
    timeline: list[TimelineEventOut]  # oldest first
