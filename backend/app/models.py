"""API response models: the allowlist of everything that leaves the backend.

Raw Stripe objects are never serialized. In particular, never add card/payment-method
details, addresses, phone numbers, metadata, receipt URLs or Stripe error bodies here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

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
    take_home: int  # after refunds and fees: what reached the balance. Minor units of reporting_currency
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
    # Every paying customer in the period, not just the `limit` returned in `customers`.
    customer_count: int


EventKind = Literal[
    "subscribed", "renewed", "subscription_changed", "purchased",
    "payment_failed", "payment_pending", "payment_canceled", "refunded",
    "disputed", "dispute_won", "dispute_inquiry",
]


class FeeOut(_Out):
    type: str  # application_fee (the platform's cut, e.g. Substack's), stripe_fee, tax, ...
    description: str | None  # Stripe's label, e.g. "Substack application fee"
    amount: int  # minor units of the reporting currency


class TimelineEventOut(_Out):
    kind: EventKind
    date: int  # unix seconds
    account_id: str
    description: str | None  # plan or invoice line, e.g. "Monthly plan" or "Founding member · yearly"
    currency: str  # currency the customer paid in
    amount: int  # payment amount, or the refund or disputed amount
    # In the reporting currency: the payment (before refunds, which are their own events), the
    # refund, or the amount a dispute withdrew or returned. Only set for successful payments.
    amount_reporting: int | None
    attempts: int  # payment attempts (retries of the same payment are one event)
    failure_message: str | None  # Stripe's customer-facing decline reason, e.g. "Your card was declined."
    # Successful payments only, in the reporting currency. fees: what this event deducted (the
    # payment's fees, or a dispute fee). take_home_before / take_home: what the payment leaves the
    # creator before and after this event; for the payment itself, take_home = amount_reporting - fees.
    fees: list[FeeOut]
    take_home_before: int | None
    take_home: int | None
    fees_not_returned: int | None  # refunds: the payment's fees, which Stripe doesn't return
    pending: bool  # a refund not yet confirmed (counted already)
    # Dispute events: Stripe's status (needs_response, under_review, won, lost, warning_* for an
    # inquiry), reason (fraudulent, product_not_received, ...) and evidence deadline. The dispute's
    # evidence (customer details) is never returned.
    dispute_status: str | None
    dispute_reason: str | None
    respond_by: int | None


class CustomerSummary(_Out):
    take_home: int  # gross - refunded - fees - disputed: what stays in the balance
    gross: int  # what the customer paid
    refunded: int
    fees: int  # platform and Stripe fees; not returned on refund
    disputed: int  # taken back by disputes (amounts and dispute fees), net of anything returned
    open_disputes: int  # disputes awaiting a response or decision
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
    lifetime_value: int  # take-home (after refunds and fees) across all time, minor units of reporting_currency
    # The subscription they have now, if any (not itself canceling). resubscribed: it started after
    # this cancellation; otherwise it was already running alongside (e.g. a second plan).
    resubscribed: bool
    current_plan: str | None
    current_since: int | None


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
    lifetime_value: int  # take-home (after refunds and fees), minor units of reporting_currency
    payment_count: int
    subscribed: bool  # has a current subscription
    accounts: list[str]


class AnniversariesResponse(_Out):
    window: Window
    since: int
    reporting_currency: str
    customers: list[AnniversaryEntry]  # most recent anniversary first


class NewCustomerEntry(_Out):
    email: str
    customer_id: str  # opaque id for the profile URL (see app/customer_id.py)
    account_id: str  # where they first paid or subscribed
    first_seen: int  # unix seconds: their first successful payment or subscription start
    # subscription: started by subscribing (including a trial). purchase: a one-off payment first,
    # e.g. a coaching session.
    started_with: Literal["subscription", "purchase"]
    description: str | None  # the plan, or what the one-off payment was for
    subscription_status: str | None  # Stripe status of their latest subscription; None if they've never subscribed
    take_home: int  # so far, after refunds, fees and disputes. Minor units of reporting_currency


class NewCustomersResponse(_Out):
    window: Window
    since: int
    reporting_currency: str
    customers: list[NewCustomerEntry]  # most recent first


RiskKind = Literal["payment_failing", "retries_exhausted", "canceling", "lapsed", "dispute"]


class AtRiskEntry(_Out):
    # payment_failing: past due, Stripe still retrying. retries_exhausted: unpaid, retries are over.
    # canceling: canceled at period end, still active. lapsed: canceled by a failed payment recently
    # and not back. dispute: a dispute or inquiry waiting on the creator's response.
    kind: RiskKind
    email: str
    customer_id: str  # opaque id for the profile URL (see app/customer_id.py)
    account_id: str
    plan: str | None  # the subscription's plan, or the disputed payment's description
    since: int  # unix seconds: the failing invoice, the cancellation, or the dispute
    deadline: int | None  # next retry, when access ends, or the evidence deadline
    amount: int | None  # owed or disputed, minor units of `currency` (the customer's)
    currency: str | None
    attempts: int | None
    failure_message: str | None  # Stripe's customer-facing decline reason
    feedback: str | None  # canceling: the customer's chosen reason, e.g. too_expensive. Never the comment.
    dispute_reason: str | None  # fraudulent, product_not_received, ...
    lifetime_value: int  # take-home across all time, minor units of reporting_currency


class AtRiskResponse(_Out):
    reporting_currency: str
    customers: list[AtRiskEntry]  # most urgent deadline first


class TrendMonthOut(_Out):
    start: int  # unix seconds: the first moment of the month, UTC
    partial: bool  # the current month, still in progress
    new_customers: int  # first successful payment or subscription this month
    churned: int  # subscribers whose access ended this month, with no other subscription running
    take_home: int  # from payments made this month, after refunds, fees and disputes. Minor units of reporting_currency


class TrendsResponse(_Out):
    reporting_currency: str
    months: list[TrendMonthOut]  # oldest first; the last is the current month
    # False without Subscriptions access: churn is then unknown, and shows as 0.
    churn_available: bool
    # Payments whose settlement currency couldn't be converted (no FX rate); excluded from take-home.
    unconverted_count: int


# --- Settings -------------------------------------------------------------------------------------
# A stored key is never returned, only its last four characters.


class MeResponse(_Out):
    email: str | None


class CredentialOut(_Out):
    id: str
    label: str | None
    stripe_account_id: str | None  # None when the key can't read its own account
    display_name: str
    settlement_currency: str
    livemode: bool
    key_type: Literal["restricted", "secret"]
    key_last4: str
    # ok; missing_permissions: works, but some views are limited; invalid: Stripe rejected the key
    status: Literal["ok", "missing_permissions", "invalid"]
    missing_permissions: list[str]
    created_at: int  # unix seconds
    last_verified_at: int  # unix seconds


class CredentialsResponse(_Out):
    credentials: list[CredentialOut]


class UserSettingsOut(_Out):
    reporting_currency: str | None  # None: the first account's payout currency


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AddCredentialRequest(_In):
    key: SecretStr = Field(max_length=255)
    label: str | None = Field(None, max_length=100)


class ReplaceKeyRequest(_In):
    key: SecretStr = Field(max_length=255)


class RenameCredentialRequest(_In):
    label: str | None = Field(None, max_length=100)


class UserSettingsIn(_In):
    reporting_currency: str | None = Field(None, pattern=r"^[a-zA-Z]{3}$")
