import { Link } from 'react-router'
import { api, WINDOWS } from '../api'
import { Chip } from '../components/Chip'
import { ListToolbar } from '../components/ListToolbar'
import { Money } from '../components/Money'
import { Segmented } from '../components/Segmented'
import { formatDate, formatRelative } from '../format'
import { startedWith, subscriptionStatus } from '../labels'
import { customerPath } from '../routes'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'
import { useListParams, useRefreshableQuery } from '../useListView'

export function NewCustomers() {
  const { value: range, account, setValue, setAccount } = useListParams('window', WINDOWS, '1m')
  const accountName = useAccountNames()
  const multipleAccounts = useMultipleAccounts()
  const { query, refresh } = useRefreshableQuery(['new-customers', range, account], (r) =>
    api.newCustomers(range, account, r),
  )

  return (
    <>
      <header className="page-header">
        <h1>New customers</h1>
        <span className="muted">First-time customers: a first subscription, trial or one-off purchase</span>
      </header>

      <ListToolbar
        picker={<Segmented options={WINDOWS} value={range} onChange={setValue} label="First seen within" />}
        account={account}
        onAccount={setAccount}
        onRefresh={refresh}
        fetching={query.isFetching}
      />

      {query.isPending && <p className="muted">Reading payments and subscriptions from Stripe…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}

      {query.data &&
        (query.data.customers.length === 0 ? (
          <p className="muted">No new customers in this period.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Started with</th>
                  <th>First seen</th>
                  <th>Subscription</th>
                  <th className="right" title="So far: after refunds, fees and disputes">
                    Take-home
                  </th>
                  {multipleAccounts && <th>Account</th>}
                </tr>
              </thead>
              <tbody>
                {query.data.customers.map((c) => {
                  const start = startedWith(c)
                  const status = c.subscription_status ? subscriptionStatus(c.subscription_status) : null
                  return (
                    <tr key={c.customer_id}>
                      <td>
                        <Link to={customerPath(c.customer_id)}>{c.email}</Link>
                      </td>
                      <td className="wrap">
                        <Chip tone={start.tone}>{start.label}</Chip> {c.description ?? <span className="muted">—</span>}
                      </td>
                      <td>
                        {formatDate(c.first_seen)}
                        <div className="muted">{formatRelative(c.first_seen)}</div>
                      </td>
                      <td>{status ? <Chip tone={status.tone}>{status.label}</Chip> : <span className="muted">None</span>}</td>
                      <td className="right">
                        <Money amount={c.take_home} currency={query.data.reporting_currency} />
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
