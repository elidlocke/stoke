import { useAuth0 } from '@auth0/auth0-react'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Outlet, useMatch, useNavigate } from 'react-router'
import { ApiError } from '../api'
import { ImportProgress } from './ImportProgress'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/actions', label: 'Actions' },
  { to: '/analytics/top', label: 'Top customers' },
  { to: '/settings', label: 'Settings' },
]

/** Until the user has added a Stripe key, any view sends them to Settings to add one. */
function useNoCredentialsRedirect() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  useEffect(
    () =>
      queryClient.getQueryCache().subscribe((event) => {
        const error = event.type === 'updated' && event.action.type === 'error' ? event.action.error : null
        if (error instanceof ApiError && error.code === 'no_credentials') navigate('/settings', { replace: true })
      }),
    [queryClient, navigate],
  )
}

/** While an account's first import runs, views answer 'importing': show its progress instead, then reload them. */
function useImporting(): [boolean, () => void] {
  const queryClient = useQueryClient()
  const [importing, setImporting] = useState(false)
  useEffect(
    () =>
      queryClient.getQueryCache().subscribe((event) => {
        const error = event.type === 'updated' && event.action.type === 'error' ? event.action.error : null
        if (error instanceof ApiError && error.code === 'importing') setImporting(true)
      }),
    [queryClient],
  )
  const done = useCallback(() => {
    setImporting(false)
    queryClient.invalidateQueries()
  }, [queryClient])
  return [importing, done]
}

export function Layout() {
  const { user, logout } = useAuth0()
  useNoCredentialsRedirect()
  const [importing, importDone] = useImporting()
  // Settings stays reachable: it's where a failed import is retried.
  const onSettings = useMatch('/settings') !== null
  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <NavLink to="/" className="brand">
            <img src="/favicon.svg" alt="" width={22} height={22} />
            Stoke
          </NavLink>
          <nav aria-label="Main">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="app-header-user">
            <span className="muted">{user?.email}</span>
            <button className="link" onClick={() => logout({ logoutParams: { returnTo: window.location.origin } })}>
              Log out
            </button>
          </div>
        </div>
      </header>
      <main>{importing && !onSettings ? <ImportProgress onDone={importDone} /> : <Outlet />}</main>
    </>
  )
}
