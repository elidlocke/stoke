import { Link } from 'react-router'
import type { Action } from '../api'
import { actionPath, actionType, isUrgent } from '../actionTypes'
import { formatRelative } from '../format'
import { Chip } from './Chip'

/** One action in the library, or recommended on Home: who's in its audience, and the first person's why. */
export function ActionCard({ action: a, recommended = false }: { action: Action; recommended?: boolean }) {
  const type = actionType(a.type)
  return (
    <Link to={actionPath(a.kind)} className="card action-card">
      <header className="card-header">
        <h3>{a.title}</h3>
        {a.unavailable ? (
          <span className="muted small">Not available</span>
        ) : (
          <span className="card-stat">
            <span className="stat-value num">{a.audience_size}</span>
            <span className="muted">{a.audience_size === 1 ? 'person' : 'people'}</span>
          </span>
        )}
      </header>
      <p className="muted small">{a.unavailable ?? a.rule}</p>
      {!a.unavailable && a.example_why && <p className="action-card-why small">“{a.example_why}”</p>}
      <p className="action-card-status small">
        <Chip tone={type.tone}>{type.label}</Chip>
        {isUrgent(a) && a.next_deadline !== null && (
          <Chip tone="bad">Soonest deadline {formatRelative(a.next_deadline)}</Chip>
        )}
        {a.enabled && <Chip tone="ok">On</Chip>}
        {a.sent > 0 && <span className="muted">{a.sent} sent</span>}
        {recommended && <span className="action-card-cta">Review & turn on →</span>}
      </p>
    </Link>
  )
}
