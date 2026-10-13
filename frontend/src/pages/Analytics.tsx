import { Navigate, useLocation, useSearchParams } from 'react-router'
import { actionPath } from '../actionTypes'

// The analytics lists that became action pages, by their old path (under /analytics, or before that at the root).
const MOVED_TO_ACTIONS: Record<string, string> = {
  new: 'welcome',
  anniversaries: 'anniversary',
  cancellations: 'win-back',
}

// At risk split into three retention actions; its filter picks which.
const AT_RISK_SHOW: Record<string, string> = { canceling: 'save', payments: 'card-failing', disputes: 'dispute-check-in' }

export const MOVED_PATHS = [...Object.keys(MOVED_TO_ACTIONS), 'at-risk']

/** Sends an old analytics address to the action that replaced it, keeping the account filter. */
export function MovedToAction({ path }: { path: string }) {
  const [params] = useSearchParams()
  const kind = path === 'at-risk' ? AT_RISK_SHOW[params.get('show') ?? ''] : MOVED_TO_ACTIONS[path]
  const account = params.get('account')
  const search = account ? `?${new URLSearchParams({ account })}` : ''
  return <Navigate to={kind ? `${actionPath(kind)}${search}` : `/actions${search}#retention`} replace />
}

/** The top customers list's address before it moved under Analytics, keeping any filters. */
export function MovedToAnalytics() {
  const { search } = useLocation()
  return <Navigate to={`/analytics/top${search}`} replace />
}
