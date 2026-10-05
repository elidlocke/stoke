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
  net_total: number
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

export interface TimelineEvent {
  kind: EventKind
  date: number
  account_id: string
  description: string | null
  currency: string // currency the customer paid in
  amount: number // payment amount, or refund amount for "refunded"
  amount_reporting: number | null // successful payments only: the payment in the reporting currency, before refunds
  attempts: number // retries of the same payment are one event
  failure_message: string | null
}

export interface CustomerProfile {
  email: string
  reporting_currency: string
  summary: {
    net: number
    gross: number
    refunded: number
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
  account_id: string
  plan: string | null
  started: number
  canceled_at: number // when the cancellation was made
  ends_at: number | null // when access ended, or will end
  ended: boolean // false: canceled at period end, still active until ends_at
  reason: string | null // cancellation_requested | payment_failed | payment_disputed
  feedback: string | null // the customer's chosen reason, e.g. too_expensive
  lifetime_value: number
  resubscribed: boolean // has another current subscription
}

export interface CancellationsResponse {
  window: Window
  since: number
  reporting_currency: string
  customers: CancellationEntry[] // most recent first
}

export interface AnniversaryEntry {
  email: string
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

export interface NewSubscriberEntry {
  email: string
  account_id: string
  plan: string | null
  started: number
  status: string // Stripe subscription status
  returning: boolean // had an earlier subscription that ended before this one started
}

export interface NewSubscribersResponse {
  window: Window
  since: number
  customers: NewSubscriberEntry[] // most recent first
}

async function get<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined) qs.set(k, v)
  const res = await fetch(qs.size ? `${path}?${qs}` : path)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${res.status})`)
  }
  return res.json()
}

export const api = {
  accounts: () => get<AccountsResponse>('/api/accounts'),
  leaderboard: (period: Period, account?: string, refresh = false) =>
    get<LeaderboardResponse>('/api/leaderboard', {
      period,
      account,
      refresh: refresh ? 'true' : undefined,
    }),
  customer: (email: string) => get<CustomerProfile>(`/api/customers/${encodeURIComponent(email)}`),
  cancellations: (window: Window, account?: string, refresh = false) =>
    get<CancellationsResponse>('/api/cancellations', { window, account, refresh: refresh ? 'true' : undefined }),
  anniversaries: (window: Window, account?: string, refresh = false) =>
    get<AnniversariesResponse>('/api/anniversaries', { window, account, refresh: refresh ? 'true' : undefined }),
  newSubscribers: (window: Window, account?: string, refresh = false) =>
    get<NewSubscribersResponse>('/api/new-subscribers', { window, account, refresh: refresh ? 'true' : undefined }),
}
