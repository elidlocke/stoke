import { Link } from 'react-router'
import { api, type AtRiskEntry, type RiskKind } from '../api'
import { Chip } from '../components/Chip'
import { ListToolbar } from '../components/ListToolbar'
import { Money } from '../components/Money'
import { Segmented } from '../components/Segmented'
import { formatDate, formatRelative } from '../format'
import { cancelReason, disputeReason, riskKind } from '../labels'
import { customerPath } from '../routes'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'
import { useListParams, useRefreshableQuery } from '../useListView'

type Show = 'all' | 'payments' | 'canceling' | 'disputes'

const SHOW: { value: Show; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'payments', label: 'Failed payments' },
  { value: 'canceling', label: 'Canceling' },
  { value: 'disputes', label: 'Disputes' },
]

const KINDS: Record<Exclude<Show, 'all'>, RiskKind[]> = {
  payments: ['payment_failing', 'retries_exhausted', 'lapsed'],
  canceling: ['canceling'],
  disputes: ['dispute'],
}

// A deadline this close (or already past) is flagged.
const SOON = 3 * 86400

function isSoon(deadline: number, now = Date.now() / 1000): boolean {
  return deadline - now < SOON
}

export function AtRisk() {
  const { value: show, account, setValue, setAccount } = useListParams('show', SHOW, 'all')
  const accountName = useAccountNames()
  const multipleAccounts = useMultipleAccounts()
  const { query, refresh } = useRefreshableQuery(['at-risk', account], (r) => api.atRisk(account, r))
  const customers = query.data?.customers.filter((c) => show === 'all' || KINDS[show].includes(c.kind))

  return (
    <>
      <header className="page-header">
        <h1>At risk</h1>
        <span className="muted">Customers you can still reach: failing payments, cancellations not yet over, and open disputes. Most urgent first</span>
      </header>

      <ListToolbar
        picker={<Segmented options={SHOW} value={show} onChange={setValue} label="Show" />}
        account={account}
        onAccount={setAccount}
        onRefresh={refresh}
        fetching={query.isFetching}
      />

      {query.isPending && <p className="muted">Reading payments and subscriptions from Stripe…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}

      {query.data &&
        customers &&
        (customers.length === 0 ? (
          <p className="muted">No one at risk right now.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Why</th>
                  <th>Plan</th>
                  <th>Act by</th>
                  <th className="right" title="Owed by the failing payment, or disputed, in the customer's currency">
                    At stake
                  </th>
                  <th className="right" title="Lifetime: everything they paid, after refunds and fees">
                    Take-home
                  </th>
                  {multipleAccounts && <th>Account</th>}
                </tr>
              </thead>
              <tbody>
                {customers.map((c, i) => {
                  const kind = riskKind(c.kind)
                  return (
                    <tr key={`${c.kind}-${c.customer_id}-${c.since}-${i}`}>
                      <td>
                        <Link to={customerPath(c.customer_id)}>{c.email}</Link>
                      </td>
                      <td className="wrap">
                        <Chip tone={kind.tone} title={kind.title}>
                          {kind.label}
                        </Chip>
                        <div className="muted">{detail(c)}</div>
                      </td>
                      <td className="wrap">{c.plan ?? <span className="muted">—</span>}</td>
                      <td>
                        <ActBy entry={c} />
                      </td>
                      <td className="right">
                        {c.amount != null && c.currency ? (
                          <Money amount={c.amount} currency={c.currency} />
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="right">
                        <Money amount={c.lifetime_value} currency={query.data.reporting_currency} />
                      </td>
                      {multipleAccounts && <td className="muted">{accountName(c.account_id)}</td>}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))}
    </>
  )
}

/** The specifics behind the risk: the decline reason, why they're canceling, or the dispute's reason. */
function detail(c: AtRiskEntry): string {
  switch (c.kind) {
    case 'payment_failing':
    case 'retries_exhausted': {
      const tries = c.attempts && c.attempts > 1 ? `${c.attempts} attempts` : null
      return [c.failure_message, tries].filter(Boolean).join(' · ') || `Failing since ${formatDate(c.since)}`
    }
    case 'canceling':
      return c.feedback
        ? cancelReason('cancellation_requested', c.feedback).label
        : `Canceled ${formatRelative(c.since)}, no reason given`
    case 'lapsed':
      return `Canceled by a failed payment ${formatRelative(c.since)}`
    case 'dispute':
      return disputeReason(c.dispute_reason) ?? `Opened ${formatRelative(c.since)}`
  }
}

/** The date to act by, with what happens then; flagged when it's close. */
function ActBy({ entry: c }: { entry: AtRiskEntry }) {
  if (c.deadline == null) {
    const what = c.kind === 'payment_failing' ? 'No retry scheduled' : 'No deadline'
    return <span className="muted">{what}</span>
  }
  const what = { payment_failing: 'Next retry', canceling: 'Access ends', dispute: 'Respond by' }[
    c.kind as 'payment_failing' | 'canceling' | 'dispute'
  ]
  const soon = isSoon(c.deadline)
  return (
    <>
      <span className="muted">{what}</span> {formatDate(c.deadline)}
      <div>
        {soon ? <Chip tone="bad">{formatRelative(c.deadline)}</Chip> : <span className="muted">{formatRelative(c.deadline)}</span>}
      </div>
    </>
  )
}
