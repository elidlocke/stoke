import { Auth0Provider, type AppState } from '@auth0/auth0-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import { ApiError } from './api'
import { AuthGate } from './components/AuthGate'
import { Layout } from './components/Layout'
import { Anniversaries } from './pages/Anniversaries'
import { AtRisk } from './pages/AtRisk'
import { Cancellations } from './pages/Cancellations'
import { CustomerProfile } from './pages/CustomerProfile'
import { Leaderboard } from './pages/Leaderboard'
import { NewCustomers } from './pages/NewCustomers'
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
                <Route path="/at-risk" element={<AtRisk />} />
                <Route path="/top" element={<Leaderboard />} />
                <Route path="/new" element={<NewCustomers />} />
                <Route path="/anniversaries" element={<Anniversaries />} />
                <Route path="/cancellations" element={<Cancellations />} />
                <Route path="/customers/:customerId" element={<CustomerProfile />} />
                <Route path="/settings" element={<Settings />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </QueryClientProvider>
      </AuthGate>
    </Auth0Provider>
  )
}
