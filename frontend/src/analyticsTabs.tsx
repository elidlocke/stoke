import { Anniversaries } from './pages/Anniversaries'
import { AtRisk } from './pages/AtRisk'
import { Cancellations } from './pages/Cancellations'
import { Leaderboard } from './pages/Leaderboard'
import { NewCustomers } from './pages/NewCustomers'

// In the order their widgets appear on the overview. Each lives at /analytics/<path>.
export const ANALYTICS_TABS = [
  { path: 'top', label: 'Top customers', element: <Leaderboard /> },
  { path: 'new', label: 'New customers', element: <NewCustomers /> },
  { path: 'anniversaries', label: 'Anniversaries', element: <Anniversaries /> },
  { path: 'cancellations', label: 'Cancellations', element: <Cancellations /> },
  { path: 'at-risk', label: 'At risk', element: <AtRisk /> },
]
