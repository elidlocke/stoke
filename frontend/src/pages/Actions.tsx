import { useEffect } from 'react'
import { Link, useLocation } from 'react-router'
import { api, type ActionType } from '../api'
import { ACTION_TYPES, byPriority } from '../actionTypes'
import { ActionCard } from '../components/ActionCard'
import { ListToolbar } from '../components/ListToolbar'
import { Segmented } from '../components/Segmented'
import { WorkingRow } from '../components/WorkingRow'
import { useListParams, useRefreshableQuery } from '../useListView'

type Filter = 'all' | ActionType

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  ...ACTION_TYPES.map((t) => ({ value: t.type, label: t.label })),
]

export function Actions() {
  const { value: filter, account, setValue, setAccount } = useListParams<Filter>('type', FILTERS, 'all')
  const { query, refresh } = useRefreshableQuery(['actions', account], (r) => api.actions(account, r))
  const { hash } = useLocation()
  // Older links to one group (e.g. #retention, #win-back) open with that type picked.
  useEffect(() => {
    const type = ACTION_TYPES.find((t) => t.type.replace('_', '-') === hash.slice(1))?.type
    if (type) setValue(type)
  }, [hash])

  const all = query.data?.actions ?? []
  const running = all.filter((a) => a.enabled)
  const shown = byPriority(all.filter((a) => filter === 'all' || a.type === filter))
  const noSources = !all.some((a) => a.type === 'cross_sell')
  const blurb = ACTION_TYPES.find((t) => t.type === filter)?.blurb

  return (
    <>
      <header className="page-header">
        <h1>Actions</h1>
        <span className="muted">Who to reach out to, and why</span>
      </header>

      <ListToolbar picker={null} account={account} onAccount={setAccount} onRefresh={refresh} fetching={query.isFetching} />

      {query.isPending && <p className="muted">Working out each action’s audience…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}

      {query.data && (
        <>
          <section className="actions-running">
            <h2 className="section-title">Running</h2>
            {running.length === 0 ? (
              <p className="muted">Nothing running yet. Start with one of the actions below.</p>
            ) : (
              <ul className="card working-list">
                {running.map((a) => (
                  <WorkingRow key={a.kind} action={a} />
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="section-title">All actions</h2>
            <div className="toolbar">
              <Segmented options={FILTERS} value={filter} onChange={setValue} label="Type of action" />
            </div>
            {blurb && <p className="muted lede-small">{blurb}</p>}
            <div className="cards action-cards">
              {shown.map((a) => (
                <ActionCard key={a.kind} action={a} />
              ))}
              {noSources && (filter === 'all' || filter === 'cross_sell') && (
                <section className="card">
                  <h3>Cross-sell what else you offer</h3>
                  <p className="muted">
                    Add a revenue stream (a course, coaching, a community) and Stoke finds the readers most likely to
                    want it.
                  </p>
                  <Link to="/settings#revenue">Add a revenue stream in Settings →</Link>
                </section>
              )}
            </div>
          </section>
        </>
      )}
    </>
  )
}
