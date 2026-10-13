import { Link, useParams } from 'react-router'
import { api } from '../api'
import { actionType } from '../actionTypes'
import { Chip } from '../components/Chip'
import { ListToolbar } from '../components/ListToolbar'
import { Money } from '../components/Money'
import { formatDate, formatRelative } from '../format'
import { customerPath } from '../routes'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'
import { useListParams, useRefreshableQuery } from '../useListView'

// A deadline this close (or already past) is flagged.
const SOON = 3 * 86400

export function Action() {
  const { kind = '' } = useParams()
  const { account, setAccount } = useListParams<string>('view', [], '') // only the account filter
  const accountName = useAccountNames()
  const multipleAccounts = useMultipleAccounts()
  const { query, refresh } = useRefreshableQuery(['action', kind, account], (r) => api.action(kind, account, r))
  const action = query.data?.action
  const retention = action?.type === 'retention'

  return (
    <>
      <Link to="/actions" className="back">
        ← All actions
      </Link>
      <header className="page-header">
        <h1>{action?.title ?? 'Action'}</h1>
        {action && <Chip tone={actionType(action.type).tone}>{actionType(action.type).label}</Chip>}
      </header>

      {action && (
        <dl className="action-facts">
          <dt>Who</dt>
          <dd>{action.rule}</dd>
          <dt>The ask</dt>
          <dd>{action.ask}</dd>
        </dl>
      )}

      <ListToolbar picker={null} account={account} onAccount={setAccount} onRefresh={refresh} fetching={query.isFetching} />

      {query.isPending && <p className="muted">Working out who’s in this audience…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}
      {action?.unavailable && <p className="warning">{action.unavailable}</p>}

      {query.data &&
        !action?.unavailable &&
        (query.data.customers.length === 0 ? (
          <p className="muted">No one in this audience right now.</p>
        ) : (
          <>
            <p className="muted">
              {query.data.customers.length} {query.data.customers.length === 1 ? 'person' : 'people'},{' '}
              {retention ? 'most urgent first' : 'highest lifetime value first'}
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th>Why this person</th>
                    <th>Plan</th>
                    {retention && <th>Act by</th>}
                    <th className="right" title="Lifetime: everything they paid, after refunds and fees">
                      Take-home
                    </th>
                    {multipleAccounts && <th>Account</th>}
                  </tr>
                </thead>
                <tbody>
                  {query.data.customers.map((c) => (
                    <tr key={`${c.customer_id}-${c.account_id}`}>
                      <td>
                        <Link to={customerPath(c.customer_id)}>{c.email}</Link>
                      </td>
                      <td className="wrap">{c.why}</td>
                      <td className="wrap">{c.plan ?? <span className="muted">—</span>}</td>
                      {retention && (
                        <td>
                          {c.deadline == null ? (
                            <span className="muted">No deadline</span>
                          ) : (
                            <>
                              {formatDate(c.deadline)}
                              <div>
                                {c.deadline - Date.now() / 1000 < SOON ? (
                                  <Chip tone="bad">{formatRelative(c.deadline)}</Chip>
                                ) : (
                                  <span className="muted">{formatRelative(c.deadline)}</span>
                                )}
                              </div>
                            </>
                          )}
                        </td>
                      )}
                      <td className="right">
                        <Money amount={c.lifetime_value} currency={query.data.reporting_currency} />
                      </td>
                      {multipleAccounts && <td className="muted">{accountName(c.account_id)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ))}
      {action?.type === 'retention' && action.kind === 'dispute-check-in' && (
        <p className="muted small">
          A note doesn’t replace a response: still submit evidence in Stripe before the deadline. A customer withdrawing
          the dispute through their bank isn’t guaranteed or instant.
        </p>
      )}
    </>
  )
}
