import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { api, type ActionAudienceResponse } from '../api'
import { actionType } from '../actionTypes'
import { Chip } from '../components/Chip'
import { ContactedChip } from '../components/ContactedChip'
import { ListToolbar } from '../components/ListToolbar'
import { Money } from '../components/Money'
import { Segmented } from '../components/Segmented'
import { formatDate, formatRelative } from '../format'
import { customerPath } from '../routes'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'
import { useListParams, useRefreshableQuery } from '../useListView'
import { History, Queue } from './ActionQueue'
import { TemplateEditor, useInvalidateAction } from './ActionTemplate'

// A deadline this close (or already past) is flagged.
const SOON = 3 * 86400

type View = 'queue' | 'audience' | 'template' | 'history'

const VIEWS: { value: View; label: string }[] = [
  { value: 'queue', label: 'Queue' },
  { value: 'audience', label: 'Audience' },
  { value: 'template', label: 'Note' },
  { value: 'history', label: 'Contacted' },
]

export function Action() {
  const { kind = '' } = useParams()
  const { query, refresh } = useRefreshableQuery(['action', kind], (r) => api.action(kind, undefined, r))
  const action = query.data?.action
  const approved = query.data?.template.approved_at != null
  const open = action?.enabled && approved
  // Turn on was clicked before the note was approved: the Note view asks for approval, which then turns it on.
  const [turningOn, setTurningOn] = useState(false)
  // Until the action is set up, the audience; then straight to the queue.
  const { value: view, account, setValue, setAccount } = useListParams('view', VIEWS, open ? 'queue' : 'audience')

  return (
    <>
      <Link to="/actions" className="back">
        ← All actions
      </Link>
      <header className="page-header">
        <h1>{action?.title ?? 'Action'}</h1>
        {action && <Chip tone={actionType(action.type).tone}>{actionType(action.type).label}</Chip>}
        {action && (
          <Toggle
            kind={kind}
            enabled={action.enabled}
            approved={approved}
            onNeedsApproval={() => {
              setTurningOn(true)
              setValue('template')
            }}
          />
        )}
      </header>

      {action && (
        <dl className="action-facts">
          <dt>Who</dt>
          <dd>{action.rule}</dd>
          <dt>The ask</dt>
          <dd>{action.ask}</dd>
          {action.sent > 0 && (
            <>
              <dt>Sent</dt>
              <dd>
                {action.sent} note{action.sent === 1 ? '' : 's'}
              </dd>
            </>
          )}
        </dl>
      )}

      {query.isPending && <p className="muted">Working out who’s in this audience…</p>}
      {query.isError && <p className="error">{query.error.message}</p>}
      {action?.unavailable && <p className="warning">{action.unavailable}</p>}

      {query.data && !action?.unavailable && (
        <>
          <div className="toolbar">
            <Segmented options={VIEWS} value={view} onChange={setValue} label="View" />
          </div>
          {view === 'queue' && <Queue kind={kind} account={account} currency={query.data.reporting_currency} />}
          {view === 'audience' && (
            <Audience data={query.data} account={account} setAccount={setAccount} onRefresh={refresh} fetching={query.isFetching} />
          )}
          {view === 'template' && <TemplateEditor
              kind={kind}
              account={account}
              template={query.data.template}
              fields={query.data.fields}
              enabled={query.data.action.enabled}
              turnOn={turningOn}
            />}
          {view === 'history' && <History kind={kind} />}
        </>
      )}
      {action?.kind === 'dispute-check-in' && (
        <p className="muted small">
          A note doesn’t replace a response: still submit evidence in Stripe before the deadline. A customer withdrawing
          the dispute through their bank isn’t guaranteed or instant.
        </p>
      )}
    </>
  )
}

/** On or off. An action is only on while its note is approved, so turning on an unapproved one goes to the note. */
function Toggle({
  kind,
  enabled,
  approved,
  onNeedsApproval,
}: {
  kind: string
  enabled: boolean
  approved: boolean
  onNeedsApproval: () => void
}) {
  const invalidate = useInvalidateAction(kind)
  const toggle = useMutation({ mutationFn: () => api.updateAction(kind, { enabled: !enabled }), onSuccess: invalidate })
  return enabled ? (
    <span>
      <Chip tone="ok">On</Chip>{' '}
      <button className="link" disabled={toggle.isPending} onClick={() => toggle.mutate()}>
        Turn off
      </button>
    </span>
  ) : (
    <button className="primary" disabled={toggle.isPending} onClick={() => (approved ? toggle.mutate() : onNeedsApproval())}>
      Turn on
    </button>
  )
}

function Audience({
  data,
  account,
  setAccount,
  onRefresh,
  fetching,
}: {
  data: ActionAudienceResponse
  account: string | undefined
  setAccount: (a: string | undefined) => void
  onRefresh: () => void
  fetching: boolean
}) {
  const accountName = useAccountNames()
  const multipleAccounts = useMultipleAccounts()
  const retention = data.action.type === 'retention'
  const customers = account ? data.customers.filter((c) => c.account_id === account) : data.customers

  return (
    <>
      <ListToolbar picker={null} account={account} onAccount={setAccount} onRefresh={onRefresh} fetching={fetching} />
      {customers.length === 0 ? (
        <p className="muted">No one in this audience right now.</p>
      ) : (
        <>
          <p className="muted">
            {customers.length} {customers.length === 1 ? 'person' : 'people'},{' '}
            {retention ? 'most urgent first' : 'highest lifetime value first'}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Why this person</th>
                  <th>Plan</th>
                  {retention && <th>Act by</th>}
                  <th className="right" title="Lifetime: everything they paid, after refunds and fees">
                    Take-home
                  </th>
                  {multipleAccounts && <th>Account</th>}
                </tr>
              </thead>
              <tbody>
                {customers.map((c) => (
                  <tr key={`${c.customer_id}-${c.account_id}`}>
                    <td>
                      <Link to={customerPath(c.customer_id)}>{c.email}</Link>
                      <div>
                        <ContactedChip customerId={c.customer_id} />
                      </div>
                    </td>
                    <td className="wrap">{c.why}</td>
                    <td className="wrap">{c.plan ?? <span className="muted">—</span>}</td>
                    {retention && (
                      <td>
                        {c.deadline == null ? (
                          <span className="muted">No deadline</span>
                        ) : (
                          <>
                            {formatDate(c.deadline)}
                            <div>
                              {c.deadline - Date.now() / 1000 < SOON ? (
                                <Chip tone="bad">{formatRelative(c.deadline)}</Chip>
                              ) : (
                                <span className="muted">{formatRelative(c.deadline)}</span>
                              )}
                            </div>
                          </>
                        )}
                      </td>
                    )}
                    <td className="right">
                      <Money amount={c.lifetime_value} currency={data.reporting_currency} />
                    </td>
                    {multipleAccounts && <td className="muted">{accountName(c.account_id)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}
