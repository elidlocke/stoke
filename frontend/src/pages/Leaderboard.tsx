import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { api, PERIODS } from '../api'
import { Money } from '../components/Money'
import { PeriodPicker } from '../components/PeriodPicker'
import { formatDate } from '../format'
import { useAccountNames } from '../useAccounts'

export function Leaderboard() {
  const [params, setParams] = useSearchParams()
  const period = PERIODS.find((p) => p.value === params.get('period'))?.value ?? '1m'
  const account = params.get('account') || undefined

  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  const accountName = useAccountNames()
  const multipleAccounts = (accounts.data?.accounts.length ?? 0) > 1
  const queryClient = useQueryClient()
  const key = ['leaderboard', period, account]
  const board = useQuery({ queryKey: key, queryFn: () => api.leaderboard(period, account) })

  const update = (next: Record<string, string | undefined>) => {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(next)) {
      if (v) p.set(k, v)
      else p.delete(k)
    }
    setParams(p, { replace: true })
  }

  const refresh = async () => {
    const data = await queryClient.fetchQuery({
      queryKey: [...key, 'refresh'],
      queryFn: () => api.leaderboard(period, account, true),
      staleTime: 0,
    })
    queryClient.setQueryData(key, data)
  }

  return (
    <>
      <header className="page-header">
        <h1>Top customers</h1>
        {board.data && (
          <span className="muted">All amounts in {board.data.reporting_currency.toUpperCase()}, net of refunds</span>
        )}
      </header>

      <div className="toolbar">
        <PeriodPicker value={period} onChange={(p) => update({ period: p })} />
        {accounts.data && multipleAccounts && (
          <select
            aria-label="Account"
            value={account ?? ''}
            onChange={(e) => update({ account: e.target.value || undefined })}
          >
            <option value="">All accounts</option>
            {accounts.data.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name}
                {a.access === 'platform' ? ' (platform)' : ''}
              </option>
            ))}
          </select>
        )}
        <button className="ghost" onClick={refresh} disabled={board.isFetching}>
          {board.isFetching ? 'Loading…' : 'Refresh'}
        </button>
      </div>

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
                        <Link to={`/customers/${encodeURIComponent(c.email)}`}>{c.email}</Link>
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
