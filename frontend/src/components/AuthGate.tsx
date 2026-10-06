import { useAuth0 } from '@auth0/auth0-react'
import type { ReactNode } from 'react'
import { setAuth } from '../api'

/** Shows the app only when signed in, and hands the API client a way to get access tokens. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { isLoading, isAuthenticated, error, loginWithRedirect, getAccessTokenSilently, logout } = useAuth0()
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
        onClick={() => loginWithRedirect({ appState: { returnTo: window.location.pathname + window.location.search } })}
      >
        Sign in
      </button>
    </div>
  )
}
