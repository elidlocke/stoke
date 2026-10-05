import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import { CustomerProfile } from './pages/CustomerProfile'
import { Leaderboard } from './pages/Leaderboard'

const queryClient = new QueryClient({
  defaultOptions: {
    // The backend caches Stripe reads; avoid refetching on every tab focus.
    queries: { staleTime: 5 * 60_000, refetchOnWindowFocus: false, retry: 1 },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <main>
          <Routes>
            <Route path="/" element={<Leaderboard />} />
            <Route path="/customers/:email" element={<CustomerProfile />} />
          </Routes>
        </main>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
