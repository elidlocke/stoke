// Mirrors backend/app/models.py. Amounts are integers in the currency's minor unit.

export type Period = '1m' | '3m' | '6m' | '12m' | 'all'

export const PERIODS: { value: Period; label: string }[] = [
  { value: '1m', label: 'Last month' },
  { value: '3m', label: '3 months' },
  { value: '6m', label: '6 months' },
  { value: '12m', label: '12 months' },
  { value: 'all', label: 'All time' },
]

// Lookback window for the event lists (cancellations, anniversaries, new subscribers).
export type Window = '7d' | '1m' | '3m'

export const WINDOWS: { value: Window; label: string }[] = [
  { value: '7d', label: 'Past week' },
  { value: '1m', label: 'Past month' },
  { value: '3m', label: 'Past 3 months' },
]

export interface Account {
  id: string
  display_name: string
  settlement_currency: string
  // platform: our Connect platform; connected: read via the platform; own_key: the account's own key
  access: 'platform' | 'connected' | 'own_key'
}

export interface AccountsResponse {
  reporting_currency: string
  accounts: Account[]
}

export interface LeaderboardEntry {
  rank: number
  email: string
  customer_id: string // opaque id for the profile URL; never the email or a Stripe id
  take_home: number // after refunds and fees: what reached the balance
  payment_count: number
  last_seen: number
  accounts: string[]
}

export interface LeaderboardResponse {
  period: Period
  since: number | null
  reporting_currency: string
  customers: LeaderboardEntry[]
  unconverted_count: number
  customer_count: number // every paying customer in the period, not just those in `customers`
}

export type EventKind =
  | 'subscribed'
  | 'renewed'
  | 'subscription_changed'
  | 'purchased'
  | 'payment_failed'
  | 'payment_pending'
  | 'payment_canceled'
  | 'refunded'
  | 'disputed' // a dispute withdrew the funds (and a dispute fee)
  | 'dispute_won' // the funds came back after a win
  | 'dispute_inquiry' // the bank asked about the payment; nothing withdrawn yet

export interface Fee {
  type: string // application_fee (the platform's cut, e.g. Substack's), stripe_fee, tax, ...
  description: string | null // Stripe's label, e.g. "Substack application fee"
  amount: number // in the reporting currency
}

export interface TimelineEvent {
  kind: EventKind
  date: number
  account_id: string
  description: string | null
  currency: string // currency the customer paid in
  amount: number // payment amount, or the refund or disputed amount
  // Successful payments only, in the reporting currency: the payment (before refunds), the
  // refund, or what a dispute withdrew or returned.
  amount_reporting: number | null
  attempts: number // retries of the same payment are one event
  failure_message: string | null
  // Successful payments only, in the reporting currency. fees: what this event deducted (the
  // payment's fees, or a dispute fee). take_home_before / take_home: what the payment leaves
  // the creator before and after this event.
  fees: Fee[]
  take_home_before: number | null
  take_home: number | null
  fees_not_returned: number | null // refunds: the payment's fees, which Stripe keeps
  pending: boolean // a refund not yet confirmed
  dispute_status: string | null // needs_response, under_review, won, lost, warning_* (inquiry)
  dispute_reason: string | null // fraudulent, product_not_received, ...
  respond_by: number | null // evidence deadline
}

export interface CustomerProfile {
  email: string
  customer_id: string // opaque id for the profile URL; never the email or a Stripe id
  reporting_currency: string
  summary: {
    take_home: number // gross - refunded - fees - disputed
    gross: number // what the customer paid
    refunded: number
    fees: number
    disputed: number // taken back by disputes, including dispute fees, net of anything returned
    open_disputes: number
    payments: number
    failed_payments: number
    first_paid: number | null
    last_paid: number | null
    current_plan: string | null
  }
  timeline: TimelineEvent[] // oldest first
}

export interface CancellationEntry {
  email: string
  customer_id: string // opaque id for the profile URL; never the email or a Stripe id
  account_id: string
  plan: string | null
  started: number
  canceled_at: number // when the cancellation was made
  ends_at: number | null // when access ended, or will end
  ended: boolean // false: canceled at period end, still active until ends_at
  reason: string | null // cancellation_requested | payment_failed | payment_disputed
  feedback: string | null // the customer's chosen reason, e.g. too_expensive
  lifetime_value: number
  // The subscription they have now, if any. resubscribed: it started after this cancellation;
  // otherwise it was already running alongside (e.g. a second plan).
  resubscribed: boolean
  current_plan: string | null
  current_since: number | null
}

export interface CancellationsResponse {
  window: Window
  since: number
  reporting_currency: string
  customers: CancellationEntry[] // most recent first
}

export interface AnniversaryEntry {
  email: string
  customer_id: string // opaque id for the profile URL; never the email or a Stripe id
  years: number
  anniversary: number
  first_paid: number
  last_paid: number
  lifetime_value: number
  payment_count: number
  subscribed: boolean // has a current subscription
  accounts: string[]
}

export interface AnniversariesResponse {
  window: Window
  since: number
  reporting_currency: string
  customers: AnniversaryEntry[] // most recent first
}

export interface NewCustomerEntry {
  email: string
  customer_id: string // opaque id for the profile URL; never the email or a Stripe id
  account_id: string // where they first paid or subscribed
  first_seen: number // their first successful payment or subscription start
  started_with: 'subscription' | 'purchase' // purchase: a one-off payment first, e.g. coaching
  description: string | null // the plan, or what the one-off payment was for
  subscription_status: string | null // their latest subscription's status; null if they've never subscribed
  take_home: number // so far, after refunds, fees and disputes
}

export interface NewCustomersResponse {
  window: Window
  since: number
  reporting_currency: string
  customers: NewCustomerEntry[] // most recent first
}

export type RiskKind = 'payment_failing' | 'retries_exhausted' | 'canceling' | 'lapsed' | 'dispute'

export interface AtRiskEntry {
  // payment_failing: past due, Stripe still retrying. retries_exhausted: unpaid, retries are over.
  // canceling: canceled at period end, still active. lapsed: canceled by a failed payment recently
  // and not back. dispute: a dispute or inquiry waiting on a response.
  kind: RiskKind
  email: string
  customer_id: string // opaque id for the profile URL; never the email or a Stripe id
  account_id: string
  plan: string | null // the subscription's plan, or the disputed payment's description
  since: number // the failing invoice, the cancellation, or the dispute
  deadline: number | null // next retry, when access ends, or the evidence deadline
  amount: number | null // owed or disputed, in `currency` (the customer's)
  currency: string | null
  attempts: number | null
  failure_message: string | null // Stripe's decline reason, e.g. "Your card was declined."
  feedback: string | null // canceling: the customer's chosen reason, e.g. too_expensive
  dispute_reason: string | null
  lifetime_value: number // take-home across all time
}

export interface AtRiskResponse {
  reporting_currency: string
  customers: AtRiskEntry[] // most urgent deadline first
}

export interface TrendMonth {
  start: number // the first moment of the month, UTC
  partial: boolean // the current month, still in progress
  new_customers: number // first successful payment or subscription this month
  churned: number // subscribers whose access ended this month, with no other subscription running
  take_home: number // from payments made this month, after refunds, fees and disputes
}

export interface TrendsResponse {
  reporting_currency: string
  months: TrendMonth[] // oldest first; the last is the current month
  churn_available: boolean // false without Subscriptions access: churn shows as 0
  unconverted_count: number // payments excluded from take-home for lack of an FX rate
}

// --- Actions ----------------------------------------------------------------------------------

export type ActionType = 'gratitude' | 'upgrade' | 'cross_sell' | 'win_back' | 'retention'

export interface Action {
  kind: string // e.g. welcome; one per revenue source: cross-sell-<link id>, repeat-booking-<link id>
  type: ActionType
  title: string
  rule: string // who's in the audience, with its thresholds
  ask: string // what the note asks for
  link_id: string | null // cross-sell: the revenue source it points at
  unavailable: string | null // why the audience can't be worked out yet; it's then empty
  audience_size: number
  enabled: boolean // turned on: its queue is open
  sent: number // notes marked sent
  open: boolean // on, with its note template approved: its queue is open
  to_send: number // open: the audience minus anyone marked sent or skipped; otherwise 0
  last_sent_at: number | null // the latest note marked sent
  next_deadline: number | null // the soonest deadline in the audience (retention)
  example_why: string | null // why the first person is in the audience
}

export interface ActionsResponse {
  reporting_currency: string
  actions: Action[] // in library order
}

export interface AudienceEntry {
  email: string
  customer_id: string // opaque id for the profile URL; never the email or a Stripe id
  account_id: string
  why: string // why this person
  plan: string | null
  lifetime_value: number // take-home across all time
  date: number // the event behind it: subscribing, an anniversary, canceling, ...
  deadline: number | null // retention: next retry, when access ends, or the evidence deadline
}

export interface MergeField {
  name: string // used as {{name}}
  description: string
  fallback: string | null // used for anyone with no value
}

export interface NoteTemplate {
  subject: string // with {{merge fields}}
  body: string
  is_default: boolean // Stoke's starting point, not edited yet
  approved_at: number | null // null: not approved (or edited since)
}

export interface ActionAudienceResponse {
  reporting_currency: string
  action: Action
  customers: AudienceEntry[] // highest value first; retention: most urgent first
  template: NoteTemplate
  fields: MergeField[] // the merge fields this action's template can use
}

export interface ActionUpdate {
  enabled?: boolean
  subject?: string
  body?: string
  approved?: boolean // approve the template as saved (after this change), or withdraw approval
}

/** A note as parts: the writer's own text, and merge-field values (`field` set) to highlight. */
export interface NotePart {
  text: string
  field: string | null
  fallback: boolean // the person has no value for the field, so its fallback was used
}

export interface QueueEntry {
  email: string
  customer_id: string
  account_id: string
  why: string
  plan: string | null
  lifetime_value: number
  deadline: number | null
  note: { subject: NotePart[]; body: NotePart[]; missing: string[] }
}

export interface QueueResponse {
  open: boolean // the action is on and its template approved
  customers: QueueEntry[] // the audience, minus anyone already marked sent or skipped
}

export interface PreviewReader {
  email: string | null // null for the example reader
  customer_id: string | null
  why: string | null
  note: { subject: NotePart[]; body: NotePart[]; missing: string[] }
}

export interface PreviewResponse {
  example: boolean // nobody is in the audience, so the note is filled for an example reader
  readers: PreviewReader[]
}

export type OutreachStatus = 'draft' | 'approved' | 'scheduled' | 'sent' | 'skipped'

export interface Outreach {
  id: string
  action_kind: string
  action_title: string
  customer_id: string
  email: string | null // null if they're no longer in the Stripe data
  status: OutreachStatus
  subject: string
  body: string
  sent_at: number | null
  created_at: number
  via_gmail: boolean // sent by Stoke from the writer's Gmail, rather than marked sent by them
}

/** The writer's Gmail, connected so Stoke can send notes from it (the gmail.send permission only). */
export interface GmailConnection {
  available: boolean // the server has Google sign-in set up
  email: string | null // null: not connected
  status: 'ok' | 'revoked' | null // revoked: Google refused Stoke's access; reconnect
  connected_at: number | null
  last_sent_at: number | null
}

export interface Contacted {
  sent_at: number // the latest note
  action_kind: string
}

// not_started: never read yet; importing: the first import (or a re-import) is running;
// ready: up to date; failed: an import stopped and needs a retry from Settings
export type SyncState = 'not_started' | 'importing' | 'ready' | 'failed'

export type SyncedObject = 'payment_intent' | 'invoice' | 'subscription' | 'customer'

export interface SyncStatus {
  accounts: {
    id: string
    display_name: string
    state: SyncState
    objects: { object: SyncedObject; state: 'pending' | 'running' | 'done' | 'skipped' | 'failed'; count: number }[]
  }[]
}

// --- Settings ---------------------------------------------------------------------------------
// A stored key is never returned, only its last four characters.

export interface Credential {
  id: string
  label: string | null
  stripe_account_id: string | null // null when the key can't read its own account
  display_name: string
  settlement_currency: string
  livemode: boolean
  key_type: 'restricted' | 'secret'
  key_last4: string
  // ok; missing_permissions: works, but some views are limited; invalid: Stripe rejected the key
  status: 'ok' | 'missing_permissions' | 'invalid'
  missing_permissions: string[]
  created_at: number
  last_verified_at: number
  sync_state: SyncState // importing the account's data into Stoke
}

export type LinkCategory = 'revenue_source' | 'social'
// How a revenue source is paid for: once (a course), per session or ticket (bookable again), or as a subscription.
export type Purchase = 'once' | 'repeat' | 'subscription'

/** One of the writer's revenue sources or social profiles. */
export interface WriterLink {
  id: string
  category: LinkCategory
  kind: string
  name: string | null
  url: string
  paid_via_account_id: string | null // revenue sources: the connected account it's paid through; null: elsewhere
  purchase: Purchase | null // revenue sources only
  created_at: number
}

export type WriterLinkIn = Omit<WriterLink, 'id' | 'created_at'>

/** A link found on the writer's Substack profile, ready to add. */
export interface LinkSuggestion {
  category: LinkCategory
  kind: string
  name: string | null
  url: string
  purchase: Purchase | null // revenue sources only
}

export interface SubstackProfile {
  name: string | null
  photo_url: string | null
  url: string // substack.com/@handle
}

export interface Substack {
  handle: string | null // null: not set yet
  profile: SubstackProfile | null // null: not set, or it couldn't be read
  suggestions: LinkSuggestion[] // links on the profile not already added
  error: string | null // why the profile couldn't be read
}

// monthly / annual: how it's billed; group: team or company plans; other: comp, gift or legacy plans.
export type PlanLabel = 'monthly' | 'annual' | 'founding' | 'group' | 'other'

/** One of the writer's subscription prices. */
export interface Plan {
  id: string // opaque; never Stripe's price id
  account_id: string
  name: string | null // as invoices show it, e.g. "Founding member · yearly"
  amount: number | null // per interval, in `currency`
  currency: string | null
  interval: string | null // day, week, month or year
  interval_count: number | null
  subscribers: number // current subscriptions on it
  label: PlanLabel | null // confirmed; null: not yet
  suggested: PlanLabel // Stoke's guess, used until it's confirmed
}

export interface PlansResponse {
  plans: Plan[] // most subscribers first
  unpriced: number // current subscriptions read before Stoke kept prices
}

/** A platform (a Stripe Connect application) that takes payments into the writer's accounts. */
export interface PaymentSource {
  id: string // opaque
  account_ids: string[]
  platform: string | null // from its fee's label, e.g. "Substack"
  payments: number
  customers: number
  last_paid: number
  example: string | null // what the latest payment was for
  // A revenue source's link id, 'newsletter' or 'other'. label: confirmed; suggested: Stoke's guess.
  label: string | null
  suggested: string | null
}

// --- Requests ---------------------------------------------------------------------------------

/** An error response. `code` is set for errors the app handles: 'no_credentials', 'importing'. */
export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

// Set by AuthGate once signed in: how to get an access token, and what to do when it's refused.
let auth: { getToken: () => Promise<string | undefined>; onUnauthorized: () => void } | null = null

export function setAuth(a: typeof auth) {
  auth = a
}

async function request<T>(
  method: string,
  path: string,
  { params, body }: { params?: Record<string, string | undefined>; body?: unknown } = {},
): Promise<T> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined) qs.set(k, v)
  const headers: Record<string, string> = {}
  const token = await auth?.getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(qs.size ? `${path}?${qs}` : path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401) auth?.onUnauthorized()
  if (!res.ok) {
    const err = await res.json().catch(() => null)
    const message = typeof err?.detail === 'string' ? err.detail : `Request failed (${res.status})`
    throw new ApiError(message, res.status, typeof err?.code === 'string' ? err.code : undefined)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

function get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  return request<T>('GET', path, { params })
}

export const api = {
  accounts: () => get<AccountsResponse>('/api/accounts'),
  leaderboard: (period: Period, account?: string, refresh = false) =>
    get<LeaderboardResponse>('/api/leaderboard', {
      period,
      account,
      refresh: refresh ? 'true' : undefined,
    }),
  customer: (customerId: string) => get<CustomerProfile>(`/api/customers/${encodeURIComponent(customerId)}`),
  cancellations: (window: Window, account?: string, refresh = false) =>
    get<CancellationsResponse>('/api/cancellations', { window, account, refresh: refresh ? 'true' : undefined }),
  anniversaries: (window: Window, account?: string, refresh = false) =>
    get<AnniversariesResponse>('/api/anniversaries', { window, account, refresh: refresh ? 'true' : undefined }),
  newCustomers: (window: Window, account?: string, refresh = false) =>
    get<NewCustomersResponse>('/api/new-customers', { window, account, refresh: refresh ? 'true' : undefined }),
  trends: () => get<TrendsResponse>('/api/trends'),
  actions: (account?: string, refresh = false) =>
    get<ActionsResponse>('/api/actions', { account, refresh: refresh ? 'true' : undefined }),
  action: (kind: string, account?: string, refresh = false) =>
    get<ActionAudienceResponse>(`/api/actions/${encodeURIComponent(kind)}`, {
      account,
      refresh: refresh ? 'true' : undefined,
    }),
  syncStatus: () => get<SyncStatus>('/api/sync-status'),
  updateAction: (kind: string, update: ActionUpdate) =>
    request<void>('PATCH', `/api/actions/${encodeURIComponent(kind)}`, { body: update }),
  queue: (kind: string, account?: string) =>
    get<QueueResponse>(`/api/actions/${encodeURIComponent(kind)}/queue`, { account }),
  previewNote: (kind: string, draft: { subject: string; body: string }, account?: string) =>
    request<PreviewResponse>('POST', `/api/actions/${encodeURIComponent(kind)}/preview`, { params: { account }, body: draft }),
  markOutreach: (
    kind: string,
    body: { customer_id: string; status: 'sent' | 'skipped'; subject?: string; body?: string },
  ) => request<Outreach>('POST', `/api/actions/${encodeURIComponent(kind)}/outreach`, { body }),
  actionOutreach: (kind: string) =>
    get<{ outreach: Outreach[] }>(`/api/actions/${encodeURIComponent(kind)}/outreach`),
  customerOutreach: (customerId: string) =>
    get<{ outreach: Outreach[] }>(`/api/customers/${encodeURIComponent(customerId)}/outreach`),
  deleteOutreach: (id: string) => request<void>('DELETE', `/api/outreach/${id}`),
  contacted: () => get<{ contacted: Record<string, Contacted> }>('/api/outreach/contacted'),
  sendNote: (kind: string, body: { customer_id: string; subject: string; body: string }) =>
    request<Outreach>('POST', `/api/actions/${encodeURIComponent(kind)}/send`, { body }),
  testNote: (kind: string, draft: { subject: string; body: string; customer_id?: string }, account?: string) =>
    request<{ to: string; reader: string | null }>('POST', `/api/actions/${encodeURIComponent(kind)}/test`, {
      params: { account },
      body: draft,
    }),
  gmail: () => get<GmailConnection>('/api/gmail'),
  connectGmail: () => request<{ url: string }>('POST', '/api/gmail/connect'),
  finishGmail: (code: string, state: string) =>
    request<GmailConnection>('POST', '/api/gmail/callback', { body: { code, state } }),
  disconnectGmail: () => request<void>('DELETE', '/api/gmail'),
  atRisk: (account?: string, refresh = false) =>
    get<AtRiskResponse>('/api/at-risk', { account, refresh: refresh ? 'true' : undefined }),
  me: () => get<{ email: string | null }>('/api/me'),
  credentials: () => get<{ credentials: Credential[] }>('/api/credentials'),
  addCredential: (key: string, label?: string) =>
    request<Credential>('POST', '/api/credentials', { body: { key, label: label || null } }),
  replaceKey: (id: string, key: string) => request<Credential>('PUT', `/api/credentials/${id}/key`, { body: { key } }),
  renameCredential: (id: string, label: string) =>
    request<Credential>('PATCH', `/api/credentials/${id}`, { body: { label: label || null } }),
  verifyCredential: (id: string) => request<Credential>('POST', `/api/credentials/${id}/verify`),
  retrySync: (id: string) => request<Credential>('POST', `/api/credentials/${id}/sync`),
  reimport: (id: string) => request<Credential>('POST', `/api/credentials/${id}/reimport`),
  deleteCredential: (id: string) => request<void>('DELETE', `/api/credentials/${id}`),
  substack: () => get<Substack>('/api/substack'),
  setSubstackHandle: (handle: string | null) => request<Substack>('PUT', '/api/substack', { body: { handle } }),
  links: () => get<{ links: WriterLink[] }>('/api/links'),
  addLink: (link: WriterLinkIn) => request<WriterLink>('POST', '/api/links', { body: link }),
  updateLink: (id: string, link: WriterLinkIn) => request<WriterLink>('PUT', `/api/links/${id}`, { body: link }),
  deleteLink: (id: string) => request<void>('DELETE', `/api/links/${id}`),
  plans: () => get<PlansResponse>('/api/plans'),
  labelPlan: (id: string, label: PlanLabel | null) => request<void>('PUT', `/api/plans/${id}`, { body: { label } }),
  paymentSources: () => get<{ sources: PaymentSource[] }>('/api/payment-sources'),
  labelPaymentSource: (id: string, label: string | null) =>
    request<void>('PUT', `/api/payment-sources/${id}`, { body: { label } }),
}
