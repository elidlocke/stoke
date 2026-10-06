import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { api, type Window } from '../api'
import { Chip } from '../components/Chip'
import { Money } from '../components/Money'
import { TrendCharts } from '../components/TrendCharts'
import { formatRelative, formatYears } from '../format'
import { cancelReason, startedWith } from '../labels'
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
        <span className="muted">Across all accounts</span>
      </header>
      <TrendCharts />
      <h2 className="section-title">The past month</h2>
      <div className="cards">
        <TopCustomersCard />
        <NewCustomersCard />
        <AnniversariesCard />
        <CancellationsCard />
      </div>
    </>
  )
}

function TopCustomersCard() {
  const q = useQuery({ queryKey: ['leaderboard', '1m', undefined], queryFn: () => api.leaderboard('1m') })
  return (
    <Card
      title="Top customers"
      to="/top"
      query={q}
      count={q.data?.customer_count}
      statLabel={(n) => `paying customer${n === 1 ? '' : 's'}`}
      empty="No paying customers this month."
    >
      {q.data?.customers.slice(0, PREVIEW).map((c) => (
        <Row key={c.email} customer={c}>
          <Money amount={c.take_home} currency={q.data.reporting_currency} />
        </Row>
      ))}
    </Card>
  )
}

function NewCustomersCard() {
  const q = useQuery({ queryKey: ['new-customers', RANGE, undefined], queryFn: () => api.newCustomers(RANGE) })
  return (
    <Card
      title="New customers"
      to="/new"
      query={q}
      count={q.data?.customers.length}
      statLabel={(n) => `new customer${n === 1 ? '' : 's'}`}
      empty="No new customers this month."
    >
      {q.data?.customers.slice(0, PREVIEW).map((c) => {
        const start = startedWith(c)
        return (
          <Row key={c.customer_id} customer={c}>
            <Chip tone={start.tone}>{start.label}</Chip>
            <span className="muted">{formatRelative(c.first_seen)}</span>
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
  statLabel,
  empty,
  children,
}: {
  title: string
  to: string
  query: { isPending: boolean; isError: boolean; error: Error | null }
  count: number | undefined
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
            <span className="stat-value num">{count}</span>
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
