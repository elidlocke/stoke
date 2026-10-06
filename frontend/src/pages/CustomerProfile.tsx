import { useQuery } from '@tanstack/react-query'
import { Fragment, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { api, type CustomerProfile as Profile, type EventKind, type Fee, type TimelineEvent } from '../api'
import { Money } from '../components/Money'
import { formatDate, formatMonth, formatRelative } from '../format'
import { disputeReason } from '../labels'
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
  disputed: { title: 'Disputed', icon: '!', tone: 'bad' },
  dispute_won: { title: 'Dispute won', icon: '↺', tone: 'ok' },
  dispute_inquiry: { title: 'Bank inquiry', icon: '?', tone: 'warn' },
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
        <Stat label="Take-home">
          <Money amount={s.take_home} currency={cur} />
        </Stat>
        <Stat label="Customer paid">
          <Money amount={s.gross} currency={cur} />
        </Stat>
        <Stat label="Fees">
          <Money amount={s.fees} currency={cur} />
        </Stat>
        <Stat label="Payments">
          <span className="num">{s.payments}</span>
        </Stat>
        {s.refunded > 0 && (
          <Stat label="Refunded">
            <Money amount={s.refunded} currency={cur} />
          </Stat>
        )}
        {(s.disputed > 0 || s.open_disputes > 0) && (
          <Stat label={s.open_disputes > 0 ? `Lost to disputes (${s.open_disputes} open)` : 'Lost to disputes'} tone="bad">
            <Money amount={s.disputed} currency={cur} />
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
  if (e.kind === 'refunded') {
    return e.pending ? { text: 'Refund processing. It’s already taken from your balance.', tone: 'neutral' } : null
  }
  if (e.kind === 'disputed' || e.kind === 'dispute_inquiry') return disputeNote(e)
  if (e.kind === 'dispute_won') return { text: 'The bank sided with you and returned the funds.', tone: 'ok' }
  if (e.amount_reporting !== null && e.attempts > 1) {
    return { text: `Went through on attempt ${e.attempts}.`, tone: 'warn' }
  }
  return null
}

function disputeNote(e: TimelineEvent): { text: string; tone: Tone } {
  const reason = disputeReason(e.dispute_reason)
  const by = e.respond_by ? ` by ${formatDate(e.respond_by)}` : ''
  const status: Record<string, { text: string; tone: Tone }> = {
    needs_response: { text: `Open: respond${by}. Counted as lost unless you win.`, tone: 'bad' },
    under_review: { text: 'Evidence submitted, awaiting the bank. Counted as lost unless you win.', tone: 'warn' },
    lost: { text: 'Lost: the funds and the dispute fee are gone.', tone: 'bad' },
    won: { text: 'Won: the funds came back, but not the dispute fee.', tone: 'neutral' },
    warning_needs_response: { text: `Nothing withdrawn yet. Respond${by} to stop it becoming a dispute.`, tone: 'warn' },
    warning_under_review: { text: 'Nothing withdrawn yet; the bank is reviewing your response.', tone: 'warn' },
    warning_closed: { text: 'Closed without becoming a dispute.', tone: 'neutral' },
  }
  const s = status[e.dispute_status ?? ''] ?? { text: `Status: ${e.dispute_status}`, tone: 'neutral' }
  return { text: reason ? `${reason}. ${s.text}` : s.text, tone: s.tone }
}

function EventAmount({ e, reportingCurrency }: { e: TimelineEvent; reportingCurrency: string }) {
  if (e.kind === 'dispute_inquiry') {
    return (
      <span className="amount unpaid" title="Nothing has been withdrawn">
        <Money amount={e.amount} currency={e.currency} />
      </span>
    )
  }
  // A refund or dispute shows how much it changed what you keep from the payment.
  if (e.take_home_before !== null && e.take_home !== null) {
    const delta = e.take_home - e.take_home_before
    return (
      <span className={delta < 0 ? 'amount bad' : 'amount ok'} title="Change to what you keep from this payment">
        {delta < 0 ? '−' : '+'}
        <Money amount={Math.abs(delta)} currency={reportingCurrency} />
      </span>
    )
  }
  if (e.kind === 'refunded') {
    return (
      <span className="amount warn">
        −<Money amount={e.amount} currency={e.currency} />
      </span>
    )
  }
  // A successful payment shows what the creator kept; the breakdown below shows what the customer paid.
  if (e.take_home !== null) {
    return (
      <span className="amount" title="What you kept, after fees">
        {e.currency !== reportingCurrency && (
          <span className="converted">
            paid <Money amount={e.amount} currency={e.currency} />
          </span>
        )}
        <Money amount={e.take_home} currency={reportingCurrency} />
      </span>
    )
  }
  const paid = e.amount_reporting !== null
  return (
    <span className={paid ? 'amount' : 'amount unpaid'}>
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
        <EventBreakdown e={e} currency={reportingCurrency} />
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
  const paid = events.reduce((sum, e) => sum + (e.amount_reporting ?? 0), 0)
  const takeHome = events.reduce((sum, e) => sum + (e.take_home ?? 0), 0)
  return (
    <li className="event">
      <Marker kind="renewed" />
      <div className="event-body">
        <div className="event-top">
          <span className="event-title">Renewed {events.length} times</span>
          <span className="amount" title="What you kept, after fees">
            <Money amount={takeHome} currency={reportingCurrency} />
          </span>
        </div>
        {first.description && <div className="event-desc">{first.description}</div>}
        <Breakdown lines={paymentLines(paid, sumFees(events))} total={takeHome} currency={reportingCurrency} />
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
                <span>
                  <Money amount={e.amount} currency={e.currency} />
                  {e.take_home !== null && (
                    <span className="muted">
                      {' '}
                      · kept <Money amount={e.take_home} currency={reportingCurrency} />
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  )
}

const FEE_LABELS: Record<string, string> = {
  application_fee: 'Platform fee',
  stripe_fee: 'Stripe processing fees',
  tax: 'Tax on fees',
}

function feeLabel(f: Fee): string {
  return f.description ?? FEE_LABELS[f.type] ?? f.type.replace(/_/g, ' ')
}

/** Fees across several payments, combined by label (e.g. all of Substack's cut in one line). */
function sumFees(events: TimelineEvent[]): Fee[] {
  const byLabel = new Map<string, Fee>()
  for (const f of events.flatMap((e) => e.fees)) {
    const key = feeLabel(f)
    const prev = byLabel.get(key)
    byLabel.set(key, { ...f, amount: (prev?.amount ?? 0) + f.amount })
  }
  return [...byLabel.values()]
}

type Line = { label: string; amount: number; sign: '+' | '−'; muted?: boolean }

function paymentLines(paid: number, fees: Fee[]): Line[] {
  return [
    { label: 'Customer paid', amount: paid, sign: '+' },
    ...fees.map((f) => ({ label: feeLabel(f), amount: f.amount, sign: '−' as const, muted: true })),
  ]
}

/**
 * Where the money went for one event. A payment: what the customer paid, each fee, what you keep.
 * A refund or dispute: what the payment left you before it, what it took (or returned), and after.
 */
function EventBreakdown({ e, currency }: { e: TimelineEvent; currency: string }) {
  if (e.take_home === null || e.amount_reporting === null) return null
  if (e.take_home_before === null) {
    return <Breakdown lines={paymentLines(e.amount_reporting, e.fees)} total={e.take_home} currency={currency} />
  }
  const lines: Line[] = [{ label: 'You kept from this payment', amount: e.take_home_before, sign: '+', muted: true }]
  if (e.kind === 'refunded') lines.push({ label: 'Refunded to the customer', amount: e.amount_reporting, sign: '−' })
  if (e.kind === 'disputed') lines.push({ label: 'Taken back by the dispute', amount: e.amount_reporting, sign: '−' })
  if (e.kind === 'dispute_won') lines.push({ label: 'Returned after the win', amount: e.amount_reporting, sign: '+' })
  for (const f of e.fees) lines.push({ label: feeLabel(f), amount: Math.abs(f.amount), sign: f.amount < 0 ? '+' : '−' })
  return (
    <>
      <Breakdown lines={lines} total={e.take_home} totalLabel="You now keep" currency={currency} />
      {e.kind === 'refunded' && !!e.fees_not_returned && (
        <div className="event-note neutral">
          The <Money amount={e.fees_not_returned} currency={currency} /> in fees on the original payment isn’t
          returned on a refund.
        </div>
      )}
    </>
  )
}

function Breakdown({
  lines,
  total,
  totalLabel = 'You keep',
  currency,
}: {
  lines: Line[]
  total: number
  totalLabel?: string
  currency: string
}) {
  return (
    <dl className="breakdown">
      {lines.map((l, i) => (
        <Fragment key={i}>
          <dt>{l.label}</dt>
          <dd className={l.muted ? 'fee' : undefined}>
            {i > 0 && l.sign}
            <Money amount={l.amount} currency={currency} />
          </dd>
        </Fragment>
      ))}
      {lines.length === 1 && (
        <>
          <dt className="muted">No fees recorded yet</dt>
          <dd />
        </>
      )}
      <dt className="total">{totalLabel}</dt>
      <dd className={total < 0 ? 'total negative' : 'total'}>
        {total < 0 && '−'}
        <Money amount={Math.abs(total)} currency={currency} />
      </dd>
    </dl>
  )
}
