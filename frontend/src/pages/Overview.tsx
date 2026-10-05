import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { api, type Window } from '../api'
import { Chip } from '../components/Chip'
import { Money } from '../components/Money'
import { formatRelative, formatYears } from '../format'
import { cancelReason, subscriptionStatus } from '../labels'
import { customerPath } from '../routes'

// The home page summarizes the past month. Query keys match the list pages' defaults,
// so opening a list after the overview is instant.
const RANGE: Window = '1m'
const PREVIEW = 5

export function Overview() {
  return (
    <>
      <header className="page-header">
        <h1>Overview</h1>
        <span className="muted">The past month across all accounts</span>
      </header>
      <div className="cards">
        <TopCustomersCard />
        <NewSubscribersCard />
        <AnniversariesCard />
        <CancellationsCard />
      </div>
    </>
  )
}

function TopCustomersCard() {
  const q = useQuery({ queryKey: ['leaderboard', '1m', undefined], queryFn: () => api.leaderboard('1m') })
  const total = q.data?.customers.reduce((sum, c) => sum + c.net_total, 0) ?? 0
  return (
    <Card
      title="Top customers"
      to="/top"
      query={q}
      count={q.data?.customers.length}
      stat={q.data && <Money amount={total} currency={q.data.reporting_currency} />}
      statLabel={(n) => (n === 1 ? 'net from your top customer' : `net from your top ${n} customers`)}
      empty="No paying customers this month."
    >
      {q.data?.customers.slice(0, PREVIEW).map((c) => (
        <Row key={c.email} customer={c}>
          <Money amount={c.net_total} currency={q.data.reporting_currency} />
        </Row>
      ))}
    </Card>
  )
}

function NewSubscribersCard() {
  const q = useQuery({ queryKey: ['new-subscribers', RANGE, undefined], queryFn: () => api.newSubscribers(RANGE) })
  return (
    <Card
      title="New subscribers"
      to="/new"
      query={q}
      count={q.data?.customers.length}
      statLabel={(n) => `new subscription${n === 1 ? '' : 's'}`}
      empty="No new subscribers this month."
    >
      {q.data?.customers.slice(0, PREVIEW).map((c, i) => {
        const status = subscriptionStatus(c.status)
        return (
          <Row key={`${c.customer_id}-${i}`} customer={c}>
            {c.status !== 'active' && <Chip tone={status.tone}>{status.label}</Chip>}
            <span className="muted">{formatRelative(c.started)}</span>
          </Row>
        )
      })}
    </Card>
  )
}

function AnniversariesCard() {
  const q = useQuery({ queryKey: ['anniversaries', RANGE, undefined], queryFn: () => api.anniversaries(RANGE) })
  return (
    <Card
      title="Anniversaries"
      to="/anniversaries"
      query={q}
      count={q.data?.customers.length}
      statLabel={(n) => `customer${n === 1 ? '' : 's'} reached a milestone`}
      empty="No anniversaries this month."
    >
      {q.data?.customers.slice(0, PREVIEW).map((c) => (
        <Row key={c.email} customer={c}>
          <Chip tone="accent">{formatYears(c.years)}</Chip>
          <span className="muted">{formatRelative(c.anniversary)}</span>
        </Row>
      ))}
    </Card>
  )
}

function CancellationsCard() {
  const q = useQuery({ queryKey: ['cancellations', RANGE, undefined], queryFn: () => api.cancellations(RANGE) })
  return (
    <Card
      title="Cancellations"
      to="/cancellations"
      query={q}
      count={q.data?.customers.length}
      statLabel={(n) => `subscription${n === 1 ? '' : 's'} canceled`}
      empty="No cancellations this month."
    >
      {q.data?.customers.slice(0, PREVIEW).map((c, i) => {
        const reason = cancelReason(c.reason, c.feedback)
        return (
          <Row key={`${c.customer_id}-${i}`} customer={c}>
            <Chip tone={reason.tone}>{reason.label}</Chip>
            <span className="muted">{formatRelative(c.canceled_at)}</span>
          </Row>
        )
      })}
    </Card>
  )
}

function Card({
  title,
  to,
  query,
  count,
  stat,
  statLabel,
  empty,
  children,
}: {
  title: string
  to: string
  query: { isPending: boolean; isError: boolean; error: Error | null }
  count: number | undefined
  stat?: ReactNode // defaults to the count
  statLabel: (count: number) => string
  empty: string
  children: ReactNode
}) {
  return (
    <section className="card">
      <header className="card-header">
        <h2>
          <Link to={to}>{title}</Link>
        </h2>
        <Link to={to} className="card-more">
          View all →
        </Link>
      </header>
      {query.isPending && <p className="muted">Loading…</p>}
      {query.isError && <p className="error">{query.error?.message}</p>}
      {count !== undefined && (
        <>
          <div className="card-stat">
            <span className="stat-value">{stat ?? <span className="num">{count}</span>}</span>
            <span className="muted">{statLabel(count)}</span>
          </div>
          {count === 0 ? <p className="muted">{empty}</p> : <ul className="card-list">{children}</ul>}
        </>
      )}
    </section>
  )
}

function Row({ customer, children }: { customer: { email: string; customer_id: string }; children: ReactNode }) {
  return (
    <li>
      <Link to={customerPath(customer.customer_id)} className="card-email">
        {customer.email}
      </Link>
      <span className="card-detail">{children}</span>
    </li>
  )
}
