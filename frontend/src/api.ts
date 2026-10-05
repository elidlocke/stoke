// Mirrors backend/app/models.py. Amounts are integers in the currency's minor unit.

export type Period = '1m' | '3m' | '6m' | '12m' | 'all'

export const PERIODS: { value: Period; label: string }[] = [
  { value: '1m', label: 'Last month' },
  { value: '3m', label: '3 months' },
  { value: '6m', label: '6 months' },
  { value: '12m', label: '12 months' },
  { value: 'all', label: 'All time' },
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
}
