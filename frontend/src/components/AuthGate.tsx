import { useAuth0 } from '@auth0/auth0-react'
import { useEffect, type ReactNode } from 'react'
import { setAuth } from '../api'

// What Auth0 adds to the URL on its way back. A code and state work once: left in the address, a reload (or
// returning there after signing in) would hand them to Auth0 again and fail with "Invalid state", every time.
const AUTH_PARAMS = ['code', 'state', 'error', 'error_description']

/** The current address without Auth0's parameters. */
function cleanUrl(): string {
  const params = new URLSearchParams(window.location.search)
  AUTH_PARAMS.forEach((p) => params.delete(p))
  const search = params.toString()
  return window.location.pathname + (search ? `?${search}` : '') + window.location.hash
}

/** Shows the app only when signed in, and hands the API client a way to get access tokens. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { isLoading, isAuthenticated, error, loginWithRedirect, getAccessTokenSilently, logout } = useAuth0()
  // After a failed return from Auth0, drop its spent parameters so the next load starts clean.
  useEffect(() => {
    if (error) window.history.replaceState(window.history.state, '', cleanUrl())
  }, [error])
  if (isLoading) return <p className="muted signin">Loading…</p>
  if (isAuthenticated) {
    // Set before the first query runs. Idempotent, so it's safe to repeat on every render.
    setAuth({
      getToken: () => getAccessTokenSilently(),
      // The API refused the token (expired session, revoked user): sign in again.
      onUnauthorized: () => logout({ logoutParams: { returnTo: window.location.origin } }),
    })
    return children
  }
  setAuth(null)

  return (
    <div className="signin">
      <h1 className="brand">
        <img src="/favicon.svg" alt="" width={26} height={26} />
        Stoke
      </h1>
      <p className="muted">Your customers across all your Stripe accounts, in one place.</p>
      {error && <p className="error">{error.message}</p>}
      <button
        className="primary"
        onClick={() => loginWithRedirect({ appState: { returnTo: cleanUrl() } })}
      >
        Sign in
      </button>
    </div>
  )
}
