import { NavLink, Navigate, Outlet, useLocation } from 'react-router'
import { ANALYTICS_TABS } from '../analyticsTabs'

export function Analytics() {
  return (
    <>
      <nav className="tabs" aria-label="Analytics">
        {ANALYTICS_TABS.map((t) => (
          <NavLink key={t.path} to={t.path}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  )
}

/** Sends an address from before the views moved under Analytics to its new one, keeping any filters. */
export function MovedToAnalytics({ path }: { path: string }) {
  const { search } = useLocation()
  return <Navigate to={`/analytics/${path}${search}`} replace />
}
