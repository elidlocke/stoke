import { Link } from 'react-router'
import { api, PERIODS } from '../api'
import { ListToolbar } from '../components/ListToolbar'
import { Money } from '../components/Money'
import { Segmented } from '../components/Segmented'
import { formatDate } from '../format'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'
import { customerPath } from '../routes'
import { useListParams, useRefreshableQuery } from '../useListView'

export function Leaderboard() {
  const { value: period, account, setValue, setAccount } = useListParams('period', PERIODS, '1m')
  const accountName = useAccountNames()
  const multipleAccounts = useMultipleAccounts()
  const { query: board, refresh } = useRefreshableQuery(['leaderboard', period, account], (r) =>
    api.leaderboard(period, account, r),
  )

  return (
    <>
      <header className="page-header">
        <h1>Top customers</h1>
        {board.data && (
          <span className="muted">All amounts in {board.data.reporting_currency.toUpperCase()}, net of refunds</span>
        )}
      </header>

      <ListToolbar
        picker={<Segmented options={PERIODS} value={period} onChange={setValue} label="Time period" />}
        account={account}
        onAccount={setAccount}
        onRefresh={refresh}
        fetching={board.isFetching}
      />

      {board.isPending && <p className="muted">Fetching payments from Stripe…</p>}
      {board.isError && <p className="error">{board.error.message}</p>}

      {board.data && (
        <>
          {board.data.unconverted_count > 0 && (
            <p className="warning">
              {board.data.unconverted_count} payment(s) couldn't be converted to{' '}
              {board.data.reporting_currency.toUpperCase()} and are excluded.
            </p>
          )}
          {board.data.customers.length === 0 ? (
            <p className="muted">No paying customers in this period.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="rank">#</th>
                    <th>Customer</th>
                    <th className="right">Net paid</th>
                    <th className="right">Payments</th>
                    <th>Last payment</th>
                    {multipleAccounts && <th>Accounts</th>}
                  </tr>
                </thead>
                <tbody>
                  {board.data.customers.map((c) => (
                    <tr key={c.email}>
                      <td className="rank num">{c.rank}</td>
                      <td>
                        <Link to={customerPath(c.customer_id)}>{c.email}</Link>
                      </td>
                      <td className="right">
                        <Money amount={c.net_total} currency={board.data.reporting_currency} />
                      </td>
                      <td className="right num">{c.payment_count}</td>
                      <td>{formatDate(c.last_seen)}</td>
                      {multipleAccounts && <td className="muted">{c.accounts.map(accountName).join(', ')}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  )
}
