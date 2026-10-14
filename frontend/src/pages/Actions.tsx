import { useEffect } from 'react'
import { Link, useLocation } from 'react-router'
import { api, type Action } from '../api'
import { ACTION_TYPES, actionPath } from '../actionTypes'
import { Chip } from '../components/Chip'
import { ListToolbar } from '../components/ListToolbar'
import { useListParams, useRefreshableQuery } from '../useListView'

export function Actions() {
  const { account, setAccount } = useListParams<string>('view', [], '') // only the account filter
  const { query, refresh } = useRefreshableQuery(['actions', account], (r) => api.actions(account, r))
  const { hash } = useLocation()
  const loaded = query.data !== undefined
  // A link to one group (e.g. #retention) scrolls to it once the library has loaded.
  useEffect(() => {
    if (loaded && hash) document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [loaded, hash])

  return (
    <>
      <header className="page-header">
        <h1>Actions</h1>
        <span className="muted">Who to reach out to, and why</span>
      </header>

      <ListToolbar picker={null} account={account} onAccount={setAccount} onRefresh={refresh} fetching={query.isFetching} />

      {query.isPending && <p className="muted">Working out each action’s audience…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}

      {query.data &&
        ACTION_TYPES.map((t) => {
          const actions = query.data.actions.filter((a) => a.type === t.type)
          const noSources = t.type === 'cross_sell' && actions.length === 0
          return (
            <section key={t.type} id={t.type.replace('_', '-')}>
              <h2 className="section-title">{t.label}</h2>
              <p className="muted lede-small">{t.blurb}</p>
              <div className="cards action-cards">
                {actions.map((a) => (
                  <ActionCard key={a.kind} action={a} />
                ))}
                {noSources && (
                  <section className="card">
                    <h3>Cross-sell what else you offer</h3>
                    <p className="muted">
                      Add a revenue stream (a course, coaching, a community) and Stoke finds the readers most likely to
                      want it.
                    </p>
                    <Link to="/settings">Add a revenue stream in Settings →</Link>
                  </section>
                )}
              </div>
            </section>
          )
        })}
    </>
  )
}

function ActionCard({ action: a }: { action: Action }) {
  return (
    <Link to={actionPath(a.kind)} className="card action-card">
      <header className="card-header">
        <h3>{a.title}</h3>
        {a.unavailable ? (
          <span className="muted small">Not available</span>
        ) : (
          <span className="card-stat">
            <span className="stat-value num">{a.audience_size}</span>
            <span className="muted">{a.audience_size === 1 ? 'person' : 'people'}</span>
          </span>
        )}
      </header>
      <p className="muted small">{a.unavailable ?? a.rule}</p>
      {(a.enabled || a.sent > 0) && (
        <p className="action-card-status small">
          {a.enabled ? <Chip tone="ok">On</Chip> : <Chip>Off</Chip>}
          {a.sent > 0 && <span className="muted">{a.sent} sent</span>}
        </p>
      )}
    </Link>
  )
}
