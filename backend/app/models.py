"""API response models: the allowlist of everything that leaves the backend.

Raw Stripe objects are never serialized. In particular, never add card/payment-method
details, addresses, phone numbers, metadata, receipt URLs or Stripe error bodies here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Period = Literal["1m", "3m", "6m", "12m", "all"]
# Lookback window for the event lists: past week, month or 3 months.
Window = Literal["7d", "1m", "3m"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountOut(_Out):
    id: str
    display_name: str
    settlement_currency: str


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
    # take_home split by where it came from; the three add up to it.
    take_home_subscriptions: int  # subscription payments
    take_home_newsletter_other: int  # the newsletter's one-offs: gifts, and payments its platform made
    take_home_other_streams: int  # sales on the writer's other revenue streams, and anything else


class TrendsResponse(_Out):
    reporting_currency: str
    months: list[TrendMonthOut]  # oldest first; the last is the current month
    # False without Subscriptions access: churn is then unknown, and shows as 0.
    churn_available: bool
    # Payments whose settlement currency couldn't be converted (no FX rate); excluded from take-home.
    unconverted_count: int


ActionType = Literal["gratitude", "upgrade", "cross_sell", "win_back", "retention"]


class ActionOut(_Out):
    kind: str  # e.g. welcome; one per revenue source: cross-sell-<link id>, repeat-booking-<link id>
    type: ActionType
    title: str
    rule: str  # who's in the audience, with its thresholds
    ask: str  # what the note asks for
    link_id: str | None  # cross-sell: the revenue source it points at
    unavailable: str | None  # why the audience can't be worked out yet; it's then empty
    audience_size: int
    enabled: bool  # turned on: its queue is open
    sent: int  # notes marked sent
    open: bool  # on, with its note template approved: its queue is open
    to_send: int  # open: the audience minus anyone marked sent or skipped (at most `batch`); otherwise 0
    batch: int | None  # the most offered to send at once, best first (free -> paid); None: everyone
    last_sent_at: int | None  # the latest note marked sent
    next_deadline: int | None  # the soonest deadline in the audience (retention)
    example_why: str | None  # why the first person is in the audience


class ActionsResponse(_Out):
    reporting_currency: str
    actions: list[ActionOut]  # in library order


class AudienceEntry(_Out):
    email: str
    customer_id: str  # opaque id for the profile URL (see app/customer_id.py)
    account_id: str
    why: str  # why this person, e.g. "3 renewals since Mar 2025, no failed payments"
    plan: str | None
    lifetime_value: int  # take-home across all time, minor units of reporting_currency
    date: int  # unix seconds: the event behind it (subscribing, an anniversary, canceling, ...)
    deadline: int | None  # retention: next retry, when access ends, or the evidence deadline
    score: float | None  # free -> paid: how likely they are to upgrade, 0-1


class MergeFieldOut(_Out):
    name: str  # used as {{name}}
    description: str
    fallback: str | None  # used for anyone with no value


class TemplateOut(_Out):
    subject: str  # with {{merge fields}}
    body: str
    is_default: bool  # Stoke's starting point, not edited yet
    approved_at: int | None  # unix seconds; None: not approved (or edited since)


class ActionAudienceResponse(_Out):
    reporting_currency: str
    action: ActionOut
    customers: list[AudienceEntry]  # highest value first; retention: most urgent first
    template: TemplateOut
    fields: list[MergeFieldOut]  # the merge fields this action's template can use


class NotePart(_Out):
    text: str
    field: str | None  # set for a merge field's value, so it can be highlighted
    fallback: bool  # the person has no value for the field, so its fallback was used


class NoteOut(_Out):
    subject: list[NotePart]
    body: list[NotePart]
    missing: list[str]  # merge fields with no value for this person, e.g. substack before it's added


class QueueEntry(_Out):
    email: str  # to address the note; never stored
    customer_id: str
    account_id: str
    why: str
    plan: str | None
    lifetime_value: int
    deadline: int | None
    score: float | None  # free -> paid: how likely they are to upgrade, 0-1
    note: NoteOut  # the template filled in for them


class QueueResponse(_Out):
    # Open once the action is on and its template approved. The queue is the audience, minus anyone
    # already marked sent or skipped for this action.
    open: bool
    customers: list[QueueEntry]


class PreviewReader(_Out):
    email: str | None  # None for the example reader
    customer_id: str | None
    why: str | None
    note: NoteOut


class PreviewResponse(_Out):
    example: bool  # nobody is in the audience, so the note is filled for an example reader
    readers: list[PreviewReader]


OutreachStatus = Literal["draft", "approved", "scheduled", "sent", "skipped"]


class OutreachOut(_Out):
    id: str
    action_kind: str
    action_title: str
    customer_id: str
    email: str | None  # looked up from the Stripe data; None if they're no longer in it
    status: OutreachStatus
    subject: str
    body: str
    sent_at: int | None  # unix seconds
    created_at: int
    via_gmail: bool  # sent by Stoke from the writer's Gmail, rather than marked sent by the writer


class OutreachResponse(_Out):
    outreach: list[OutreachOut]  # newest first


class ContactedOut(_Out):
    sent_at: int  # unix seconds: the latest note
    action_kind: str


class ContactedResponse(_Out):
    contacted: dict[str, ContactedOut]  # by customer id


# not_started: never read yet; importing: the first import (or a re-import) is running;
# ready: up to date; failed: an import stopped and needs a retry from Settings
SyncState = Literal["not_started", "importing", "ready", "failed"]


class ObjectSyncOut(_Out):
    object: Literal["payment_intent", "invoice", "subscription", "customer"]
    state: Literal["pending", "running", "done", "skipped", "failed"]
    count: int  # imported so far


class AccountSyncOut(_Out):
    id: str
    display_name: str
    state: SyncState
    objects: list[ObjectSyncOut]


class SyncStatusResponse(_Out):
    accounts: list[AccountSyncOut]


# --- Settings -------------------------------------------------------------------------------------
# A stored secret is never returned: for a key, only its last four characters.


class MeResponse(_Out):
    email: str | None


class CredentialOut(_Out):
    id: str
    label: str | None
    stripe_account_id: str | None  # None when a key can't read its own account
    display_name: str
    settlement_currency: str
    livemode: bool
    # oauth: connected with the Stripe App. restricted, secret: a key added before the app.
    key_type: Literal["oauth", "restricted", "secret"]
    key_last4: str | None  # keys only
    # ok; missing_permissions: works, but some views are limited; invalid: Stripe refused the key, or the app was
    # uninstalled
    status: Literal["ok", "missing_permissions", "invalid"]
    missing_permissions: list[str]
    created_at: int  # unix seconds
    last_verified_at: int  # unix seconds
    sync_state: SyncState  # importing the account's data into Stoke


class CredentialsResponse(_Out):
    credentials: list[CredentialOut]
    connect_available: bool  # whether this server can connect Stripe accounts (the Stripe App is configured)


class StripeConnectOut(_Out):
    url: str  # the Stripe App's install page


class UserSettingsOut(_Out):
    reporting_currency: str | None  # None: the first account's payout currency


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RenameCredentialRequest(_In):
    label: str | None = Field(None, max_length=100)


class UserSettingsIn(_In):
    reporting_currency: str | None = Field(None, pattern=r"^[a-zA-Z]{3}$")


# --- The writer's links: revenue sources and social profiles (audience channels) ------------

LinkCategory = Literal["revenue_source", "social"]
Purchase = Literal["once", "repeat", "subscription"]

LINK_KINDS: dict[str, set[str]] = {
    "revenue_source": {"calendly", "maven", "gumroad", "teachable", "circle", "luma", "book", "other"},  # the platform it's sold on
    "social": {
        "substack", "x", "instagram", "linkedin", "youtube", "tiktok", "threads", "bluesky", "facebook",
        "podcast", "website", "other",
    },
}

# How a revenue source is usually bought, when the writer doesn't say.
DEFAULT_PURCHASE: dict[str, Purchase] = {"calendly": "repeat", "luma": "repeat", "circle": "subscription"}


class LinkOut(_Out):
    id: str
    category: LinkCategory
    kind: str
    name: str | None
    url: str
    paid_via_account_id: str | None  # revenue sources: the connected account it's paid through; None: elsewhere
    purchase: Purchase | None  # revenue sources only
    created_at: int  # unix seconds


class LinksResponse(_Out):
    links: list[LinkOut]


class LinkSuggestion(_Out):
    """A link found on the writer's Substack profile, ready to add (POST /api/links)."""
    category: LinkCategory
    kind: str
    name: str | None
    url: str
    purchase: Purchase | None = None  # revenue sources only


# --- The writer's Substack ------------------------------------------------------------------------

class SubstackProfileOut(_Out):
    name: str | None
    photo_url: str | None
    url: str  # their profile, substack.com/@handle


class SubstackPublicationOut(_Out):
    subdomain: str  # its name on substack.com, for links to its dashboard; free subscriber lists are keyed by it
    name: str | None
    url: str  # its home page


class SubstackOut(_Out):
    handle: str | None  # None: not set yet
    profile: SubstackProfileOut | None  # None: not set, or it couldn't be read
    suggestions: list[LinkSuggestion]  # links on the profile not already added
    publications: list[SubstackPublicationOut]  # the ones the writer runs, primary first
    error: str | None  # why the profile couldn't be read; the writer adds links by hand


class SubstackIn(_In):
    handle: str | None = Field(None, max_length=200)  # "@you", "you" or substack.com/@you; None: forget it


class SubstackListOut(_Out):
    """One publication's free subscribers, uploaded from its Substack export."""
    publication: str  # its subdomain
    exported_at: int  # unix seconds: from the export's filename, else when it was uploaded
    uploaded_at: int
    free_count: int


class SubstackListIn(_In):
    filename: str = Field(max_length=200)
    csv: str = Field(max_length=25_000_000)


class LinkIn(_In):
    category: LinkCategory
    kind: str = Field(max_length=40)
    name: str | None = Field(None, max_length=120)
    url: str = Field(max_length=2000, pattern=r"^https://[^\s/]+\.[^\s]+$")
    paid_via_account_id: str | None = Field(None, max_length=255)
    purchase: Purchase | None = None

    @model_validator(mode="after")
    def _check(self) -> "LinkIn":
        if self.kind not in LINK_KINDS[self.category]:
            raise ValueError(f"Unknown {self.category} type")
        self.name = self.name or None
        if self.category == "revenue_source":
            if self.name is None:
                raise ValueError("A revenue source needs a name")
            self.purchase = self.purchase or DEFAULT_PURCHASE.get(self.kind, "once")
        elif self.paid_via_account_id is not None or self.purchase is not None:
            raise ValueError("Only revenue sources are paid for")
        return self


# --- The writer's profile: plan labels and where payments come from -------------------------------
# Prices and Connect applications are referred to by opaque ids (app/customer_id.py: ref_id), never Stripe's.

# monthly / annual: how it's billed; group: team or company plans; other: comp, gift or legacy plans.
PlanLabel = Literal["monthly", "annual", "founding", "group", "other"]


class PlanOut(_Out):
    id: str  # opaque
    account_id: str
    name: str | None  # as invoices show it, e.g. "Founding member · yearly"
    amount: int | None  # per interval, minor units of `currency`
    currency: str | None
    interval: str | None  # day, week, month or year
    interval_count: int | None
    subscribers: int  # current subscriptions on it
    label: PlanLabel | None  # confirmed by the writer; None: not yet
    suggested: PlanLabel  # Stoke's guess, used until it's confirmed


class PlansResponse(_Out):
    plans: list[PlanOut]  # most subscribers first
    # Current subscriptions read before Stoke kept prices: their plans appear once they're read again.
    unpriced: int


class PlanLabelIn(_In):
    label: PlanLabel | None  # None: back to Stoke's guess


class PaymentSourceOut(_Out):
    id: str  # opaque: the Connect application that created the payments
    account_ids: list[str]
    platform: str | None  # from its fee's label, e.g. "Substack"
    payments: int
    customers: int
    last_paid: int  # unix seconds
    example: str | None  # what the latest payment was for
    # A revenue source's link id, "newsletter", or "other". label: confirmed; suggested: Stoke's guess.
    label: str | None
    suggested: str | None


class PaymentSourcesResponse(_Out):
    sources: list[PaymentSourceOut]  # most payments first


class PaymentSourceLabelIn(_In):
    label: str | None = Field(None, max_length=64)  # a revenue source's link id, "newsletter", "other", or None


# --- Actions and outreach -------------------------------------------------------------------------

class ActionUpdate(_In):
    enabled: bool | None = None
    subject: str | None = Field(None, max_length=300)
    body: str | None = Field(None, max_length=10_000)
    approved: bool | None = None  # approve the template as saved (after this change), or withdraw approval


class PreviewIn(_In):
    subject: str = Field("", max_length=300)
    body: str = Field("", max_length=10_000)


class GmailOut(_Out):
    available: bool  # the server has a Google OAuth client set up
    email: str | None  # the connected Gmail address; None: not connected
    status: Literal["ok", "revoked"] | None  # revoked: Google refused Stoke's access; reconnect
    connected_at: int | None
    last_sent_at: int | None


class GmailConnectOut(_Out):
    url: str  # Google's consent page


class TestNoteIn(_In):
    subject: str = Field("", max_length=300)
    body: str = Field("", max_length=10_000)
    customer_id: str | None = Field(None, pattern=r"^[0-9a-f]{24}$")  # whose copy; None: the first in the audience


class TestNoteOut(_Out):
    to: str  # the writer's Gmail address
    reader: str | None  # whose copy it is; None for the example reader


class SendNoteIn(_In):
    customer_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    subject: str = Field(min_length=1, max_length=300)  # as it'll be sent, after any edits
    body: str = Field(min_length=1, max_length=10_000)


class OutreachIn(_In):
    customer_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    status: Literal["sent", "skipped"]  # sent: the writer sent it themselves; skipped: left out
    subject: str = Field("", max_length=300)  # as sent, after any edits
    body: str = Field("", max_length=10_000)
