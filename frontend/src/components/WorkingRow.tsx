import { Link } from 'react-router'
import type { Action } from '../api'
import { actionPath } from '../actionTypes'
import { formatRelative } from '../format'

/** An action that's on (so its note is approved): what's left to send and what's been sent. Only what Stoke can track. */
export function WorkingRow({ action: a }: { action: Action }) {
  return (
    <li className="card working-row">
      <div className="working-what">
        <Link to={actionPath(a.kind)} className="working-title">
          {a.title}
        </Link>
        <span className="muted small">
          {a.to_send} to send · {a.sent} sent
          {a.last_sent_at !== null && ` · last sent ${formatRelative(a.last_sent_at)}`}
        </span>
      </div>
      {a.to_send > 0 && (
        <Link to={`${actionPath(a.kind)}?view=queue`} className="button ghost">
          Open queue
        </Link>
      )}
    </li>
  )
}
