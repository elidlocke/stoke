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
}

export interface UserSettings {
  reporting_currency: string | null // null: the first account's payout currency
}

// --- Requests ---------------------------------------------------------------------------------

/** An error response. `code` is set for errors the app handles, e.g. 'no_credentials'. */
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
  deleteCredential: (id: string) => request<void>('DELETE', `/api/credentials/${id}`),
  settings: () => get<UserSettings>('/api/settings'),
  saveSettings: (s: UserSettings) => request<UserSettings>('PUT', '/api/settings', { body: s }),
}
