import { Auth0Provider, type AppState } from '@auth0/auth0-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import { ApiError } from './api'
import { AuthGate } from './components/AuthGate'
import { Layout } from './components/Layout'
import { ANALYTICS_TABS } from './analyticsTabs'
import { Analytics, MovedToAnalytics } from './pages/Analytics'
import { CustomerProfile } from './pages/CustomerProfile'
import { Overview } from './pages/Overview'
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
                <Route path="/" element={<Overview />} />
                <Route path="/analytics" element={<Analytics />}>
                  <Route index element={<Navigate to={ANALYTICS_TABS[0].path} replace />} />
                  {ANALYTICS_TABS.map((t) => (
                    <Route key={t.path} path={t.path} element={t.element} />
                  ))}
                </Route>
                <Route path="/customers/:customerId" element={<CustomerProfile />} />
                <Route path="/settings" element={<Settings />} />
                {/* The views' addresses before they moved under Analytics, so old links still work. */}
                {ANALYTICS_TABS.map((t) => (
                  <Route key={t.path} path={`/${t.path}`} element={<MovedToAnalytics path={t.path} />} />
                ))}
              </Route>
            </Routes>
          </BrowserRouter>
        </QueryClientProvider>
      </AuthGate>
    </Auth0Provider>
  )
}
