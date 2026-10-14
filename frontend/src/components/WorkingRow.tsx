import { Link } from 'react-router'
import type { Action } from '../api'
import { actionPath } from '../actionTypes'
import { formatRelative } from '../format'

/** An action that's on: what's left to send and what's been sent. Only what Stoke can track. */
export function WorkingRow({ action: a }: { action: Action }) {
  return (
    <li className="working-row">
      <div className="working-what">
        <Link to={actionPath(a.kind)} className="working-title">
          {a.title}
        </Link>
        <span className="muted small">
          {a.open ? `${a.to_send} to send` : 'Note not approved yet'} · {a.sent} sent
          {a.last_sent_at !== null && ` · last sent ${formatRelative(a.last_sent_at)}`}
        </span>
      </div>
      {a.open ? (
        a.to_send > 0 && (
          <Link to={`${actionPath(a.kind)}?view=queue`} className="button ghost">
            Open queue
          </Link>
        )
      ) : (
        <Link to={`${actionPath(a.kind)}?view=template`} className="button ghost">
          Approve note
        </Link>
      )}
    </li>
  )
}
