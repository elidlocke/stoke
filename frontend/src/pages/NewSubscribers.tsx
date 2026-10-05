import { Link } from 'react-router'
import { api, WINDOWS } from '../api'
import { Chip } from '../components/Chip'
import { ListToolbar } from '../components/ListToolbar'
import { Segmented } from '../components/Segmented'
import { formatDate, formatRelative } from '../format'
import { subscriptionStatus } from '../labels'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'
import { useListParams, useRefreshableQuery } from '../useListView'

export function NewSubscribers() {
  const { value: range, account, setValue, setAccount } = useListParams('window', WINDOWS, '1m')
  const accountName = useAccountNames()
  const multipleAccounts = useMultipleAccounts()
  const { query, refresh } = useRefreshableQuery(['new-subscribers', range, account], (r) =>
    api.newSubscribers(range, account, r),
  )

  return (
    <>
      <header className="page-header">
        <h1>New subscribers</h1>
        <span className="muted">Subscriptions started recently, most recent first</span>
      </header>

      <ListToolbar
        picker={<Segmented options={WINDOWS} value={range} onChange={setValue} label="Subscribed within" />}
        account={account}
        onAccount={setAccount}
        onRefresh={refresh}
        fetching={query.isFetching}
      />

      {query.isPending && <p className="muted">Reading subscriptions from Stripe…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}

      {query.data &&
        (query.data.customers.length === 0 ? (
          <p className="muted">No new subscribers in this period.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Plan</th>
                  <th>Subscribed</th>
                  <th>Status</th>
                  {multipleAccounts && <th>Account</th>}
                </tr>
              </thead>
              <tbody>
                {query.data.customers.map((c, i) => {
                  const status = subscriptionStatus(c.status)
                  return (
                    <tr key={`${c.email}-${c.started}-${i}`}>
                      <td>
                        <Link to={`/customers/${encodeURIComponent(c.email)}`}>{c.email}</Link>
                        {c.returning && (
                          <>
                            {' '}
                            <Chip tone="accent" title="Had an earlier subscription that ended">
                              Returning
                            </Chip>
                          </>
                        )}
                      </td>
                      <td className="wrap">{c.plan ?? <span className="muted">—</span>}</td>
                      <td>
                        {formatDate(c.started)} <span className="muted">· {formatRelative(c.started)}</span>
                      </td>
                      <td>
                        <Chip tone={status.tone}>{status.label}</Chip>
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
