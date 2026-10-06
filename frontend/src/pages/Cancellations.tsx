import { Link } from 'react-router'
import { api, WINDOWS } from '../api'
import { Chip } from '../components/Chip'
import { ListToolbar } from '../components/ListToolbar'
import { Money } from '../components/Money'
import { Segmented } from '../components/Segmented'
import { formatDate, formatRelative } from '../format'
import { cancelReason } from '../labels'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'
import { customerPath } from '../routes'
import { useListParams, useRefreshableQuery } from '../useListView'

export function Cancellations() {
  const { value: range, account, setValue, setAccount } = useListParams('window', WINDOWS, '1m')
  const accountName = useAccountNames()
  const multipleAccounts = useMultipleAccounts()
  const { query, refresh } = useRefreshableQuery(['cancellations', range, account], (r) =>
    api.cancellations(range, account, r),
  )

  return (
    <>
      <header className="page-header">
        <h1>Cancellations</h1>
        <span className="muted">Subscriptions canceled recently, most recent first</span>
      </header>

      <ListToolbar
        picker={<Segmented options={WINDOWS} value={range} onChange={setValue} label="Canceled within" />}
        account={account}
        onAccount={setAccount}
        onRefresh={refresh}
        fetching={query.isFetching}
      />

      {query.isPending && <p className="muted">Reading subscriptions from Stripe…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}

      {query.data &&
        (query.data.customers.length === 0 ? (
          <p className="muted">No cancellations in this period.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Plan</th>
                  <th>Canceled</th>
                  <th>Access</th>
                  <th>Reason</th>
                  <th className="right" title="Lifetime: everything they paid, after refunds and fees">Take-home</th>
                  {multipleAccounts && <th>Account</th>}
                </tr>
              </thead>
              <tbody>
                {query.data.customers.map((c, i) => {
                  const reason = cancelReason(c.reason, c.feedback)
                  return (
                    <tr key={`${c.email}-${c.canceled_at}-${i}`}>
                      <td>
                        <Link to={customerPath(c.customer_id)}>{c.email}</Link>
                      </td>
                      <td className="wrap">{c.plan ?? <span className="muted">—</span>}</td>
                      <td>
                        {formatDate(c.canceled_at)}
                        <div className="muted">{formatRelative(c.canceled_at)}</div>
                      </td>
                      <td className="wrap">
                        {c.ended ? (
                          <span className="muted">Ended{c.ends_at && ` ${formatDate(c.ends_at)}`}</span>
                        ) : (
                          <Chip tone="warn" title="Canceled at period end: still subscribed until then">
                            Active until {c.ends_at ? formatDate(c.ends_at) : 'period end'}
                          </Chip>
                        )}
                        {c.current_since != null && (
                          <div className="access-now">
                            <Chip
                              tone="ok"
                              title={
                                c.resubscribed
                                  ? 'Came back with a new subscription after canceling'
                                  : 'Has another subscription that was already running'
                              }
                            >
                              {c.resubscribed ? `Resubscribed ${formatDate(c.current_since)}` : 'Still subscribed'}
                            </Chip>
                            {c.current_plan && <div className="muted">{c.current_plan}</div>}
                          </div>
                        )}
                      </td>
                      <td>
                        <Chip tone={reason.tone}>{reason.label}</Chip>
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
