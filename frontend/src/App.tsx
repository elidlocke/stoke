import { Auth0Provider, type AppState } from '@auth0/auth0-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { ApiError } from './api'
import { AuthGate } from './components/AuthGate'
import { Layout } from './components/Layout'
import { Action } from './pages/Action'
import { Actions } from './pages/Actions'
import { MOVED_PATHS, MovedToAction, MovedToAnalytics } from './pages/Analytics'
import { CustomerProfile } from './pages/CustomerProfile'
import { Home } from './pages/Home'
import { Leaderboard } from './pages/Leaderboard'
import { Settings } from './pages/Settings'

const queryClient = new QueryClient({
  defaultOptions: {
    // The backend caches Stripe reads; avoid refetching on every tab focus.
    queries: {
      staleTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      // Retrying won't fix being signed out, a missing key, or a bad request.
      retry: (failures, error) => failures < 1 && !(error instanceof ApiError && (error.status < 500 || error.code)),
    },
  },
})

// After signing in, return to the page the user was on.
function onRedirectCallback(appState?: AppState) {
  window.history.replaceState({}, '', appState?.returnTo ?? '/')
}

export default function App() {
  return (
    <Auth0Provider
      domain={import.meta.env.VITE_AUTH0_DOMAIN}
      clientId={import.meta.env.VITE_AUTH0_CLIENT_ID}
      authorizationParams={{ audience: import.meta.env.VITE_AUTH0_AUDIENCE, redirect_uri: window.location.origin }}
      // Tokens stay in memory; a refresh token (rotated by Auth0) keeps the session across reloads.
      useRefreshTokens
      onRedirectCallback={onRedirectCallback}
    >
      <AuthGate>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <Routes>
              <Route element={<Layout />}>
                <Route path="/" element={<Home />} />
                <Route path="/actions" element={<Actions />} />
                <Route path="/actions/:kind" element={<Action />} />
                <Route path="/analytics" element={<Navigate to="/analytics/top" replace />} />
                <Route path="/analytics/top" element={<Leaderboard />} />
                <Route path="/customers/:customerId" element={<CustomerProfile />} />
                <Route path="/settings" element={<Settings />} />
                {/* Old addresses, so links still work: the lists that became actions, and the views before Analytics. */}
                <Route path="/top" element={<MovedToAnalytics />} />
                {MOVED_PATHS.flatMap((p) => [
                  <Route key={`a-${p}`} path={`/analytics/${p}`} element={<MovedToAction path={p} />} />,
                  <Route key={p} path={`/${p}`} element={<MovedToAction path={p} />} />,
                ])}
              </Route>
            </Routes>
          </BrowserRouter>
        </QueryClientProvider>
      </AuthGate>
    </Auth0Provider>
  )
}
