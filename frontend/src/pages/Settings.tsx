import { useIsFetching, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'
import { api, type Credential } from '../api'
import { Chip } from '../components/Chip'
import { formatRelative } from '../format'
import { useOAuthOutcome, type Outcome } from '../useOAuthOutcome'
import { GmailSettings } from './SettingsGmail'
import { AudienceChannels, RevenueStreams } from './SettingsLinks'
import { Plans } from './SettingsProfile'
import { SubstackProfile } from './SettingsSubstack'

// How connecting went, from ?stripe= on Stripe's way back through the API (routers/stripe_app.py).
const OUTCOMES: Record<string, Outcome> = {
  connected: { ok: true, message: 'Stripe connected. Stoke is importing your history.' },
  denied: { ok: false, message: 'Stripe wasn’t connected: you cancelled at Stripe.' },
  expired: { ok: false, message: 'That Stripe connection took too long. Try connecting again.' },
  invalid: { ok: false, message: 'That Stripe connection couldn’t be checked. Try connecting again from this browser.' },
  too_many: { ok: false, message: 'You’ve connected as many Stripe accounts as Stoke allows.' },
  failed: { ok: false, message: 'Stripe didn’t accept that connection. Try connecting again.' },
}

export function Settings() {
  useScrollToSection()
  return (
    <>
      <header className="page-header">
        <h1>Settings</h1>
      </header>
      {/* In the order a writer needs them: connect their data, check what Stoke found, then start sending. */}
      <h2 className="settings-group">Connect</h2>
      <div className="settings-grid">
        <SubstackProfile />
        <StripeAccounts />
      </div>
      <h2 className="settings-group">Refine what Stoke found</h2>
      <div className="settings-grid">
        <Plans />
        <RevenueStreams />
        <AudienceChannels />
      </div>
      <h2 className="settings-group">Start engaging</h2>
      <div className="settings-grid">
        <GmailSettings />
      </div>
    </>
  )
}

/** A link from Home (e.g. /settings#plans) scrolls to its section once, after the sections above it have loaded. */
function useScrollToSection() {
  const { hash } = useLocation()
  const idle = useIsFetching() === 0
  const done = useRef<string | null>(null)
  useEffect(() => {
    if (!idle || !hash || done.current === hash) return
    done.current = hash
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [idle, hash])
}

/** Every view reads from the accounts in scope, so any change here refreshes them all. */
function useInvalidateAll() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries()
}

/** Sends the writer to Stripe to install Stoke's app; they come back through the API to Settings. */
function useConnectStripe() {
  return useMutation({
    mutationFn: api.connectStripe,
    onSuccess: ({ url }) => window.location.assign(url),
  })
}

function StripeAccounts() {
  const creds = useQuery({
    queryKey: ['credentials'],
    queryFn: api.credentials,
    // Follow an import until it finishes.
    refetchInterval: (q) => (q.state.data?.credentials.some((c) => c.sync_state === 'importing') ? 3000 : false),
  })
  const list = creds.data?.credentials ?? []
  const { hash } = useLocation()
  const outcome = useOAuthOutcome('stripe', OUTCOMES, 'failed')
  return (
    <section className="settings-section full">
      <h2 id="stripe">
        2 · Your Stripe accounts {list.some((c) => c.status !== 'invalid') && <Chip tone="ok">Connected</Chip>}
      </h2>
      <p className="muted lede-small">
        Connect Stripe so Stoke can segment your paid subscribers. Stoke installs as a read-only Stripe app: you see
        exactly what it can read before you approve.
      </p>
      {outcome && <p className={outcome.ok ? 'muted' : 'error'}>{outcome.message}</p>}
      {creds.isError && <p className="error">{creds.error.message}</p>}
      {list.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Connection</th>
                <th>Status</th>
                <th className="right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <CredentialRow key={c.id} cred={c} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creds.isSuccess && <ConnectStripe first={list.length === 0} available={creds.data.connect_available} />}
      {/* Arriving from the Welcome page: once an account is in, point back to where the actions are. */}
      {hash === '#stripe' && list.length > 0 && (
        <p>
          <Link to="/">Back to Home to see your actions →</Link>
        </p>
      )}
    </section>
  )
}

function keyPrefix(c: Credential) {
  return `${c.key_type === 'secret' ? 'sk' : 'rk'}_${c.livemode ? 'live' : 'test'}_…${c.key_last4}`
}

function Status({ cred }: { cred: Credential }) {
  if (cred.status === 'invalid')
    return cred.key_type === 'oauth' ? (
      <Chip tone="bad" title="Stoke’s Stripe app was uninstalled from this account, or Stripe stopped its access.">
        Disconnected in Stripe
      </Chip>
    ) : (
      <Chip tone="bad" title="Stripe no longer accepts this key. It may have been rolled or deleted.">
        Rejected by Stripe
      </Chip>
    )
  if (cred.status === 'missing_permissions')
    return (
      <Chip tone="warn" title={`Stoke can’t read: ${cred.missing_permissions.join(', ')}`}>
        Missing {cred.missing_permissions.join(', ')}
      </Chip>
    )
  return <Chip tone="ok">Ready</Chip>
}

/** Importing the account's payments and subscriptions into Stoke. */
function ImportState({ cred }: { cred: Credential }) {
  const invalidateAll = useInvalidateAll()
  const retry = useMutation({ mutationFn: () => api.retrySync(cred.id), onSuccess: invalidateAll })
  if (cred.status === 'invalid') return null
  if (cred.sync_state === 'failed')
    return (
      <div className="small">
        <span className="error">Import failed.</span>{' '}
        <button className="link" onClick={() => retry.mutate()} disabled={retry.isPending}>
          Retry
        </button>
        {retry.isError && <div className="error">{retry.error.message}</div>}
      </div>
    )
  return (
    <div className="muted small">{cred.sync_state === 'ready' ? 'Up to date' : 'Importing from Stripe…'}</div>
  )
}

type Editing = 'edit' | 'remove' | null

function CredentialRow({ cred }: { cred: Credential }) {
  const invalidateAll = useInvalidateAll()
  const [editing, setEditing] = useState<Editing>(null)
  const verify = useMutation({ mutationFn: () => api.verifyCredential(cred.id), onSuccess: invalidateAll })
  const reimport = useMutation({ mutationFn: () => api.reimport(cred.id), onSuccess: invalidateAll })
  const connect = useConnectStripe()
  const isApp = cred.key_type === 'oauth'
  // An app that was uninstalled is reconnected; a key that Stripe refused can't be fixed by checking it again.
  const reconnect = !isApp || cred.status === 'invalid'

  return (
    <>
      <tr>
        <td className="wrap">
          <div>
            {cred.label ?? cred.display_name} <Chip tone={cred.livemode ? 'accent' : 'neutral'}>{cred.livemode ? 'Live' : 'Test'}</Chip>
          </div>
          <div className="muted small">
            {cred.label ? `${cred.display_name} · ` : ''}
            {cred.stripe_account_id ?? 'Account id unknown (needs Accounts: Read)'}
          </div>
        </td>
        <td>
          {isApp ? (
            'Stripe app'
          ) : (
            <>
              <code>{keyPrefix(cred)}</code>
              <div>
                <Chip tone="warn" title="Keys added by hand are being replaced by Stoke’s read-only Stripe app.">
                  Switch to the Stripe app
                </Chip>
              </div>
            </>
          )}
        </td>
        <td className="wrap">
          <Status cred={cred} />
          {cred.status !== 'ok' && !(isApp && cred.status === 'invalid') && (
            <>
              {' '}
              <span className="small">
                <button className="link" onClick={() => verify.mutate()} disabled={verify.isPending}>
                  {verify.isPending ? 'Checking…' : 'Re-check'}
                </button>
              </span>
            </>
          )}
          <ImportState cred={cred} />
          <div className="muted small">Checked {formatRelative(cred.last_verified_at)}</div>
          {verify.isError && <div className="error small">{verify.error.message}</div>}
          {reimport.isError && <div className="error small">{reimport.error.message}</div>}
          {connect.isError && <div className="error small">{connect.error.message}</div>}
        </td>
        <td className="right actions">
          {reconnect && (
            <button className="link" onClick={() => connect.mutate()} disabled={connect.isPending}>
              {connect.isPending ? 'Opening Stripe…' : isApp ? 'Reconnect' : 'Switch to the Stripe app'}
            </button>
          )}
          {cred.status !== 'invalid' && (
            <button
              className="link"
              title="Read this account’s history from Stripe again, for when recent payments are missing"
              onClick={() => reimport.mutate()}
              disabled={reimport.isPending || cred.sync_state === 'importing'}
            >
              {cred.sync_state === 'importing' ? 'Importing…' : 'Re-import'}
            </button>
          )}
          <button className="link" onClick={() => setEditing(editing === 'edit' ? null : 'edit')}>
            Rename
          </button>
          <button className="link danger" onClick={() => setEditing(editing === 'remove' ? null : 'remove')}>
            Remove
          </button>
        </td>
      </tr>
      {editing && (
        <tr className="edit-row">
          <td colSpan={4}>
            {editing === 'edit' && <RenameForm cred={cred} onDone={() => setEditing(null)} />}
            {editing === 'remove' && <RemoveConfirm cred={cred} onDone={() => setEditing(null)} />}
          </td>
        </tr>
      )}
    </>
  )
}

function RenameForm({ cred, onDone }: { cred: Credential; onDone: () => void }) {
  const invalidateAll = useInvalidateAll()
  const [label, setLabel] = useState(cred.label ?? '')
  const save = useMutation({
    mutationFn: (v: string) => api.renameCredential(cred.id, v),
    onSettled: invalidateAll,
    onSuccess: onDone,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate(label.trim())
  }
  return (
    <form className="inline-form" onSubmit={submit}>
      <label>
        Name shown in Stoke
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={cred.display_name} maxLength={100} autoFocus />
      </label>
      <button className="primary" disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>
      <button type="button" className="ghost" onClick={onDone}>Cancel</button>
      {save.isError && <p className="error">{save.error.message}</p>}
    </form>
  )
}

function RemoveConfirm({ cred, onDone }: { cred: Credential; onDone: () => void }) {
  const invalidateAll = useInvalidateAll()
  const remove = useMutation({ mutationFn: () => api.deleteCredential(cred.id), onSuccess: invalidateAll })
  return (
    <div className="inline-form">
      <span>
        Remove {cred.label ?? cred.display_name}? Its customers will no longer appear in Stoke.{' '}
        {cred.key_type === 'oauth'
          ? 'To stop Stoke’s access entirely, also uninstall Stoke from your Stripe Dashboard’s installed apps.'
          : 'The key is deleted from Stoke; to stop it working entirely, also delete it in your Stripe Dashboard.'}
      </span>
      <button className="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
        Remove
      </button>
      <button className="ghost" onClick={onDone}>Cancel</button>
      {remove.isError && <p className="error">{remove.error.message}</p>}
    </div>
  )
}

function ConnectStripe({ first, available }: { first: boolean; available: boolean }) {
  const connect = useConnectStripe()
  if (!available) return <p className="muted">Connecting Stripe isn’t set up on this server yet.</p>
  return (
    <div className="connect-stripe card">
      <h3>{first ? 'Connect your Stripe account' : 'Connect another Stripe account'}</h3>
      <p className="muted">
        You’ll choose the account on Stripe and approve Stoke’s read-only access, then come back here. Stoke can’t
        move money or change anything in Stripe.
      </p>
      <button className="primary" disabled={connect.isPending} onClick={() => connect.mutate()}>
        {connect.isPending ? 'Opening Stripe…' : 'Connect with Stripe'}
      </button>
      {connect.isError && <p className="error">{connect.error.message}</p>}
    </div>
  )
}
