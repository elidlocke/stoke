import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { api, type CustomerProfile as Profile, type EventKind, type TimelineEvent } from '../api'
import { Money } from '../components/Money'
import { formatDate, formatMonth, formatRelative } from '../format'
import { useAccountNames } from '../useAccounts'

type Tone = 'ok' | 'bad' | 'warn' | 'neutral'

const KIND: Record<EventKind, { title: string; icon: string; tone: Tone }> = {
  subscribed: { title: 'Subscribed', icon: '★', tone: 'ok' },
  renewed: { title: 'Renewed', icon: '↻', tone: 'ok' },
  subscription_changed: { title: 'Changed plan', icon: '⇄', tone: 'ok' },
  purchased: { title: 'Paid', icon: '✓', tone: 'ok' },
  payment_failed: { title: 'Payment failed', icon: '✕', tone: 'bad' },
  payment_pending: { title: 'Payment processing', icon: '…', tone: 'neutral' },
  payment_canceled: { title: 'Payment canceled', icon: '–', tone: 'neutral' },
  refunded: { title: 'Refunded', icon: '↩', tone: 'warn' },
}

// Runs of this many or more identical renewals collapse into one "Renewed N times" entry.
const COLLAPSE_RENEWALS = 3

type Item =
  | { type: 'event'; event: TimelineEvent }
  | { type: 'renewals'; events: TimelineEvent[] }

function sameRenewal(a: TimelineEvent, b: TimelineEvent) {
  return (
    a.kind === 'renewed' &&
    b.kind === 'renewed' &&
    a.description === b.description &&
    a.amount === b.amount &&
    a.currency === b.currency &&
    a.account_id === b.account_id
  )
}

function toItems(events: TimelineEvent[]): Item[] {
  const items: Item[] = []
  for (let i = 0; i < events.length; ) {
    let j = i + 1
    while (j < events.length && sameRenewal(events[i], events[j])) j++
    if (j - i >= COLLAPSE_RENEWALS) items.push({ type: 'renewals', events: events.slice(i, j) })
    else for (const event of events.slice(i, j)) items.push({ type: 'event', event })
    i = j
  }
  return items
}

function groupByMonth(items: Item[]): { month: string; items: Item[] }[] {
  const groups: { month: string; items: Item[] }[] = []
  for (const item of items) {
    const date = item.type === 'event' ? item.event.date : item.events[0].date
    const month = formatMonth(date)
    if (groups.at(-1)?.month === month) groups.at(-1)!.items.push(item)
    else groups.push({ month, items: [item] })
  }
  return groups
}

export function CustomerProfile() {
  const customerId = useParams().customerId ?? ''
  const [order, setOrder] = useState<'oldest' | 'newest'>('oldest')
  const profile = useQuery({ queryKey: ['customer', customerId], queryFn: () => api.customer(customerId) })

  return (
    <>
      <BackLink />
      <header className="page-header">
        <h1>{profile.data?.email ?? 'Customer'}</h1>
      </header>

      {profile.isPending && <p className="muted">Reading this customer's history from Stripe…</p>}
      {profile.isError && <p className="error">{profile.error.message}</p>}

      {profile.data && (
        <>
          <Summary profile={profile.data} />

          {profile.data.timeline.length === 0 ? (
            <p className="muted">No payments yet.</p>
          ) : (
            <>
              <div className="timeline-header">
                <h2>History</h2>
                <div className="segmented" role="radiogroup" aria-label="Order">
                  {(['oldest', 'newest'] as const).map((o) => (
                    <button
                      key={o}
                      role="radio"
                      aria-checked={order === o}
                      className={order === o ? 'active' : ''}
                      onClick={() => setOrder(o)}
                    >
                      {o === 'oldest' ? 'Oldest first' : 'Newest first'}
                    </button>
                  ))}
                </div>
              </div>
              <Timeline
                events={order === 'oldest' ? profile.data.timeline : [...profile.data.timeline].reverse()}
                reportingCurrency={profile.data.reporting_currency}
              />
            </>
          )}
        </>
      )}
    </>
  )
}

/** Returns to whichever list the customer was opened from; to the overview on a direct visit. */
function BackLink() {
  const navigate = useNavigate()
  const location = useLocation()
  const hasHistory = location.key !== 'default'
  return (
    <a
      href="/"
      className="back"
      onClick={(e) => {
        e.preventDefault()
        if (hasHistory) navigate(-1)
        else navigate('/')
      }}
    >
      ← Back
    </a>
  )
}

function Summary({ profile }: { profile: Profile }) {
  const s = profile.summary
  const cur = profile.reporting_currency
  return (
    <section className="summary">
      <p className="lede">
        {s.first_paid ? (
          <>
            Paying customer since <strong>{formatDate(s.first_paid)}</strong> ({formatRelative(s.first_paid)})
            {s.last_paid && s.last_paid !== s.first_paid && <>, last paid {formatRelative(s.last_paid)}</>}.
            {s.current_plan && (
              <>
                {' '}
                Most recent plan: <strong>{s.current_plan}</strong>.
              </>
            )}
          </>
        ) : (
          <>Hasn't completed a payment yet.</>
        )}
      </p>
      <div className="stats">
        <Stat label="Lifetime value">
          <Money amount={s.net} currency={cur} />
        </Stat>
        <Stat label="Payments">
          <span className="num">{s.payments}</span>
        </Stat>
        {s.refunded > 0 && (
          <Stat label="Refunded">
            <Money amount={s.refunded} currency={cur} />
          </Stat>
        )}
        {s.failed_payments > 0 && (
          <Stat label="Failed payments" tone="bad">
            <span className="num">{s.failed_payments}</span>
          </Stat>
        )}
      </div>
    </section>
  )
}

function Stat({ label, tone, children }: { label: string; tone?: Tone; children: ReactNode }) {
  return (
    <div className={`stat ${tone ?? ''}`}>
      <div className="stat-value">{children}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}

function Timeline({ events, reportingCurrency }: { events: TimelineEvent[]; reportingCurrency: string }) {
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const accountName = useAccountNames()
  const showAccount = (accounts.data?.accounts.length ?? 0) > 1

  return (
    <div className="timeline">
      {groupByMonth(toItems(events)).map((group) => (
        <section key={group.month} className="timeline-month">
          <h3>{group.month}</h3>
          <ol>
            {group.items.map((item, i) =>
              item.type === 'event' ? (
                <EventItem
                  key={i}
                  event={item.event}
                  reportingCurrency={reportingCurrency}
                  account={showAccount ? accountName(item.event.account_id) : null}
                />
              ) : (
                <RenewalRun
                  key={i}
                  events={item.events}
                  reportingCurrency={reportingCurrency}
                  account={showAccount ? accountName(item.events[0].account_id) : null}
                />
              ),
            )}
          </ol>
        </section>
      ))}
    </div>
  )
}

function Marker({ kind }: { kind: EventKind }) {
  const { icon, tone } = KIND[kind]
  return (
    <span className={`marker ${tone}`} aria-hidden>
      {icon}
    </span>
  )
}

function note(e: TimelineEvent): { text: string; tone: Tone } | null {
  if (e.kind === 'payment_failed') {
    const tries = e.attempts > 1 ? `Tried ${e.attempts} times. ` : ''
    return { text: `${tries}${e.failure_message ?? ''}`.trim(), tone: 'bad' }
  }
  if (e.kind === 'payment_canceled') return { text: 'Canceled before it was paid.', tone: 'neutral' }
  if (e.amount_reporting !== null && e.attempts > 1) {
    return { text: `Went through on attempt ${e.attempts}.`, tone: 'warn' }
  }
  return null
}

function EventAmount({ e, reportingCurrency }: { e: TimelineEvent; reportingCurrency: string }) {
  if (e.kind === 'refunded') {
    return (
      <span className="amount warn">
        −<Money amount={e.amount} currency={e.currency} />
      </span>
    )
  }
  const paid = e.amount_reporting !== null
  return (
    <span className={paid ? 'amount' : 'amount unpaid'}>
      {paid && e.currency !== reportingCurrency && (
        <span className="converted">
          ≈ <Money amount={e.amount_reporting!} currency={reportingCurrency} />
        </span>
      )}
      <Money amount={e.amount} currency={e.currency} />
    </span>
  )
}

function EventItem({
  event: e,
  reportingCurrency,
  account,
}: {
  event: TimelineEvent
  reportingCurrency: string
  account: string | null
}) {
  const n = note(e)
  return (
    <li className="event">
      <Marker kind={e.kind} />
      <div className="event-body">
        <div className="event-top">
          <span className="event-title">{KIND[e.kind].title}</span>
          <EventAmount e={e} reportingCurrency={reportingCurrency} />
        </div>
        {e.description && <div className="event-desc">{e.description}</div>}
        {n && <div className={`event-note ${n.tone}`}>{n.text}</div>}
        <div className="event-meta">
          <time dateTime={new Date(e.date * 1000).toISOString()}>{formatDate(e.date)}</time>
          {' · '}
          {formatRelative(e.date)}
          {account && <> · {account}</>}
        </div>
      </div>
    </li>
  )
}

function RenewalRun({
  events,
  reportingCurrency,
  account,
}: {
  events: TimelineEvent[]
  reportingCurrency: string
  account: string | null
}) {
  const [open, setOpen] = useState(false)
  const first = events[0]
  const dates = events.map((e) => e.date)
  const total = events.reduce((sum, e) => sum + (e.amount_reporting ?? 0), 0)
  return (
    <li className="event">
      <Marker kind="renewed" />
      <div className="event-body">
        <div className="event-top">
          <span className="event-title">Renewed {events.length} times</span>
          <span className="amount">
            <Money amount={total} currency={reportingCurrency} />
          </span>
        </div>
        {first.description && <div className="event-desc">{first.description}</div>}
        <div className="event-meta">
          {formatDate(Math.min(...dates))} – {formatDate(Math.max(...dates))}
          {account && <> · {account}</>}
          {' · '}
          <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? 'Hide each renewal' : 'Show each renewal'}
          </button>
        </div>
        {open && (
          <ul className="renewals">
            {events.map((e, i) => (
              <li key={i}>
                <span>{formatDate(e.date)}</span>
                <Money amount={e.amount} currency={e.currency} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  )
}
