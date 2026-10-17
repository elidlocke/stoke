import { useAuth0 } from '@auth0/auth0-react'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { NavLink, Outlet, useMatch, useNavigate } from 'react-router'
import { ApiError } from '../api'
import { SITE_LINKS, signedOutUrl, siteUrl } from '../site'
import { ImportProgress } from './ImportProgress'

// The brand links to Home.
const NAV = [
  { to: '/actions', label: 'Actions' },
  { to: '/customers', label: 'Customers' },
  { to: '/settings', label: 'Settings' },
]

/** Until the user has added a Stripe key, any view sends them to Home, which welcomes them and points to Settings. */
function useNoCredentialsRedirect() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  useEffect(
    () =>
      queryClient.getQueryCache().subscribe((event) => {
        const error = event.type === 'updated' && event.action.type === 'error' ? event.action.error : null
        if (!(error instanceof ApiError && error.code === 'no_credentials')) return
        if (window.location.pathname !== '/' && window.location.pathname !== '/settings') navigate('/', { replace: true })
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
              <NavLink key={n.to} to={n.to}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="app-header-user">
            <span className="muted">{user?.email}</span>
            <button className="link" onClick={() => logout({ logoutParams: { returnTo: signedOutUrl() } })}>
              Log out
            </button>
          </div>
        </div>
      </header>
      <main>{importing && !onSettings ? <ImportProgress onDone={importDone} /> : <Outlet />}</main>
      <footer className="app-footer">
        {SITE_LINKS.map((l) => (
          <a key={l.path} href={siteUrl(l.path)}>
            {l.label}
          </a>
        ))}
      </footer>
    </>
  )
}
