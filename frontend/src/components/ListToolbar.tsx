import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { api } from '../api'

/** The picker for a list's time range, an account filter (when there's more than one), and Refresh. */
export function ListToolbar({
  picker,
  account,
  onAccount,
  onRefresh,
  fetching,
}: {
  picker: ReactNode
  account: string | undefined
  onAccount: (a: string | undefined) => void
  onRefresh: () => void
  fetching: boolean
}) {
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: api.accounts })
  return (
    <div className="toolbar">
      {picker}
      {accounts.data && accounts.data.accounts.length > 1 && (
        <select aria-label="Account" value={account ?? ''} onChange={(e) => onAccount(e.target.value || undefined)}>
          <option value="">All accounts</option>
          {accounts.data.accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.display_name}
              {a.access === 'platform' ? ' (platform)' : ''}
            </option>
          ))}
        </select>
      )}
      <button className="ghost" onClick={onRefresh} disabled={fetching}>
        {fetching ? 'Loading…' : 'Refresh'}
      </button>
    </div>
  )
}
