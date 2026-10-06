import { useAuth0 } from '@auth0/auth0-react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router'
import { ApiError } from '../api'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/at-risk', label: 'At risk' },
  { to: '/top', label: 'Top customers' },
  { to: '/new', label: 'New customers' },
  { to: '/anniversaries', label: 'Anniversaries' },
  { to: '/cancellations', label: 'Cancellations' },
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

export function Layout() {
  const { user, logout } = useAuth0()
  useNoCredentialsRedirect()
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
      <main>
        <Outlet />
      </main>
    </>
  )
}
