import { Link } from 'react-router'
import { api, WINDOWS } from '../api'
import { Chip } from '../components/Chip'
import { ListToolbar } from '../components/ListToolbar'
import { Money } from '../components/Money'
import { Segmented } from '../components/Segmented'
import { formatDate, formatRelative, formatYears } from '../format'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'
import { useListParams, useRefreshableQuery } from '../useListView'

export function Anniversaries() {
  const { value: range, account, setValue, setAccount } = useListParams('window', WINDOWS, '1m')
  const accountName = useAccountNames()
  const multipleAccounts = useMultipleAccounts()
  const { query, refresh } = useRefreshableQuery(['anniversaries', range, account], (r) =>
    api.anniversaries(range, account, r),
  )

  return (
    <>
      <header className="page-header">
        <h1>Anniversaries</h1>
        <span className="muted">Customers who recently reached a year (or more) since their first payment</span>
      </header>

      <ListToolbar
        picker={<Segmented options={WINDOWS} value={range} onChange={setValue} label="Anniversary within" />}
        account={account}
        onAccount={setAccount}
        onRefresh={refresh}
        fetching={query.isFetching}
      />

      {query.isPending && <p className="muted">Reading payment history from Stripe…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}

      {query.data &&
        (query.data.customers.length === 0 ? (
          <p className="muted">No anniversaries in this period.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Milestone</th>
                  <th>Anniversary</th>
                  <th>Customer since</th>
                  <th className="right">Lifetime value</th>
                  <th className="right">Payments</th>
                  <th>Status</th>
                  {multipleAccounts && <th>Accounts</th>}
                </tr>
              </thead>
              <tbody>
                {query.data.customers.map((c) => (
                  <tr key={c.email}>
                    <td>
                      <Link to={`/customers/${encodeURIComponent(c.email)}`}>{c.email}</Link>
                    </td>
                    <td>
                      <Chip tone="accent">{formatYears(c.years)}</Chip>
                    </td>
                    <td>
                      {formatDate(c.anniversary)} <span className="muted">· {formatRelative(c.anniversary)}</span>
                    </td>
                    <td>{formatDate(c.first_paid)}</td>
                    <td className="right">
                      <Money amount={c.lifetime_value} currency={query.data.reporting_currency} />
                    </td>
                    <td className="right num">{c.payment_count}</td>
                    <td>
                      {c.subscribed ? (
                        <Chip tone="ok">Subscribed</Chip>
                      ) : (
                        <span className="muted">Last paid {formatRelative(c.last_paid)}</span>
                      )}
                    </td>
                    {multipleAccounts && <td className="muted">{c.accounts.map(accountName).join(', ')}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </>
  )
}
