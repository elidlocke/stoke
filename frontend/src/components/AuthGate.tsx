import { GenericError, MissingRefreshTokenError, useAuth0 } from '@auth0/auth0-react'
import { useEffect, type ReactNode } from 'react'
import { setAuth } from '../api'
import { SITE_LINKS, signedOutUrl, siteUrl } from '../site'

// Auth0's errors for a session that's over and needs a fresh sign-in.
const SESSION_ENDED = ['invalid_grant', 'login_required']

// What Auth0 adds to the URL on its way back. A code and state work once: left in the address, a reload (or
// returning there after signing in) would hand them to Auth0 again and fail with "Invalid state", every time.
const AUTH_PARAMS = ['code', 'state', 'error', 'error_description']

// The public site's Get started links here with ?signup (and ?plan=<tier>, kept for billing later).
const SIGNUP_PARAMS = ['signup', 'plan']

/** The current address without Auth0's (or the sign-up link's) parameters. */
function cleanUrl(): string {
  const params = new URLSearchParams(window.location.search)
  for (const p of [...AUTH_PARAMS, ...SIGNUP_PARAMS]) params.delete(p)
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
  // Arriving from Get started: go straight to Auth0's sign-up screen.
  const signingUp = !isLoading && !isAuthenticated && !error && new URLSearchParams(window.location.search).has('signup')
  useEffect(() => {
    if (!signingUp) return
    const plan = new URLSearchParams(window.location.search).get('plan')
    loginWithRedirect({ authorizationParams: { screen_hint: 'signup' }, appState: { returnTo: cleanUrl(), plan } })
  }, [signingUp, loginWithRedirect])
  if (signingUp) return <p className="muted signin">Opening sign-up…</p>
  if (isLoading) return <p className="muted signin">Loading…</p>
  if (isAuthenticated) {
    // Set before the first query runs. Idempotent, so it's safe to repeat on every render.
    const signOut = () => logout({ logoutParams: { returnTo: signedOutUrl() } })
    setAuth({
      // A session Auth0 can't renew (no refresh token stored, or it was revoked or rotated away): sign in again,
      // rather than every query failing with Auth0's message.
      getToken: () =>
        getAccessTokenSilently().catch((e: unknown) => {
          if (e instanceof MissingRefreshTokenError || (e instanceof GenericError && SESSION_ENDED.includes(e.error)))
            signOut()
          throw e
        }),
      // The API refused the token (expired session, revoked user): sign in again.
      onUnauthorized: signOut,
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
      <p className="muted">
        New to Stoke?{' '}
        <button
          className="link"
          onClick={() =>
            loginWithRedirect({ authorizationParams: { screen_hint: 'signup' }, appState: { returnTo: cleanUrl() } })
          }
        >
          Create an account
        </button>
      </p>
      <nav className="signin-links" aria-label="About Stoke">
        <a href={siteUrl('/')}>About Stoke</a>
        {SITE_LINKS.map((l) => (
          <a key={l.path} href={siteUrl(l.path)}>
            {l.label}
          </a>
        ))}
      </nav>
    </div>
  )
}
