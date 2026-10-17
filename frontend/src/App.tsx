import { Auth0Provider, type AppState } from '@auth0/auth0-react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import { ApiError } from './api'
import { AuthGate } from './components/AuthGate'
import { Layout } from './components/Layout'
import { Action } from './pages/Action'
import { Actions } from './pages/Actions'
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
      // Tokens are kept in localStorage, so the session survives reloads and full-page trips (e.g. connecting Gmail).
      // Auth0 rotates the refresh token on every use and revokes the whole family if an old one is replayed, which
      // limits what a stolen token is worth. In memory only, every page load signed the writer out.
      useRefreshTokens
      cacheLocation="localstorage"
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
                <Route path="/customers" element={<Leaderboard />} />
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
