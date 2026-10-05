import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { Anniversaries } from './pages/Anniversaries'
import { Cancellations } from './pages/Cancellations'
import { CustomerProfile } from './pages/CustomerProfile'
import { Leaderboard } from './pages/Leaderboard'
import { NewSubscribers } from './pages/NewSubscribers'
import { Overview } from './pages/Overview'

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
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Overview />} />
            <Route path="/top" element={<Leaderboard />} />
            <Route path="/new" element={<NewSubscribers />} />
            <Route path="/anniversaries" element={<Anniversaries />} />
            <Route path="/cancellations" element={<Cancellations />} />
            <Route path="/customers/:email" element={<CustomerProfile />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
