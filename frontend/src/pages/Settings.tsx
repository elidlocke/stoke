import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, type Credential } from '../api'
import { Chip } from '../components/Chip'
import { formatRelative } from '../format'

// Common payout currencies; "Automatic" uses the first account's.
const CURRENCIES = ['usd', 'eur', 'gbp', 'cad', 'aud', 'nzd', 'chf', 'sek', 'nok', 'dkk', 'jpy', 'sgd', 'inr', 'brl', 'mxn']

const PERMISSIONS = [
  'PaymentIntents',
  'Invoices',
  'Charges',
  'Customers',
  'Subscriptions',
  'Balance transactions',
  'Accounts',
]

export function Settings() {
  return (
    <>
      <header className="page-header">
        <h1>Settings</h1>
      </header>
      <StripeAccounts />
      <ReportingCurrency />
    </>
  )
}

/** Every view reads from the accounts in scope, so any change here refreshes them all. */
function useInvalidateAll() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries()
}

function StripeAccounts() {
  const creds = useQuery({ queryKey: ['credentials'], queryFn: api.credentials })
  const list = creds.data?.credentials ?? []
  return (
    <section className="settings-section">
      <h2>Stripe accounts</h2>
      <p className="muted lede-small">
        Add a key for each Stripe account you sell through. Stoke only reads from Stripe. Keys are encrypted before
        they're stored and are never shown again, only their last four characters.
      </p>
      {creds.isError && <p className="error">{creds.error.message}</p>}
      {list.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Key</th>
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
      {creds.isSuccess && <AddCredential first={list.length === 0} />}
    </section>
  )
}

function keyPrefix(c: Credential) {
  return `${c.key_type === 'secret' ? 'sk' : 'rk'}_${c.livemode ? 'live' : 'test'}_…${c.key_last4}`
}

function Status({ cred }: { cred: Credential }) {
  if (cred.status === 'invalid')
    return (
      <Chip tone="bad" title="Stripe no longer accepts this key. It may have been rolled or deleted.">
        Rejected by Stripe
      </Chip>
    )
  if (cred.status === 'missing_permissions')
    return (
      <Chip tone="warn" title={`Grant Read access to: ${cred.missing_permissions.join(', ')}`}>
        Missing {cred.missing_permissions.join(', ')}
      </Chip>
    )
  return <Chip tone="ok">Ready</Chip>
}

type Editing = 'rename' | 'replace' | 'remove' | null

function CredentialRow({ cred }: { cred: Credential }) {
  const invalidateAll = useInvalidateAll()
  const [editing, setEditing] = useState<Editing>(null)
  const verify = useMutation({ mutationFn: () => api.verifyCredential(cred.id), onSuccess: invalidateAll })

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
          <code>{keyPrefix(cred)}</code>
          {cred.key_type === 'secret' && (
            <div>
              <Chip tone="warn" title="A secret key can change your Stripe account. Stoke only needs to read.">
                Use a restricted key
              </Chip>
            </div>
          )}
        </td>
        <td className="wrap">
          <Status cred={cred} />
          <div className="muted small">Checked {formatRelative(cred.last_verified_at)}</div>
          {verify.isError && <div className="error small">{verify.error.message}</div>}
        </td>
        <td className="right actions">
          <button className="link" onClick={() => setEditing(editing === 'rename' ? null : 'rename')}>
            Rename
          </button>
          <button className="link" onClick={() => setEditing(editing === 'replace' ? null : 'replace')}>
            Replace key
          </button>
          <button className="link" onClick={() => verify.mutate()} disabled={verify.isPending}>
            {verify.isPending ? 'Checking…' : 'Re-check'}
          </button>
          <button className="link danger" onClick={() => setEditing(editing === 'remove' ? null : 'remove')}>
            Remove
          </button>
        </td>
      </tr>
      {editing && (
        <tr className="edit-row">
          <td colSpan={4}>
            {editing === 'rename' && <RenameForm cred={cred} onDone={() => setEditing(null)} />}
            {editing === 'replace' && <ReplaceForm cred={cred} onDone={() => setEditing(null)} />}
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
  const rename = useMutation({
    mutationFn: () => api.renameCredential(cred.id, label.trim()),
    onSuccess: () => {
      invalidateAll()
      onDone()
    },
  })
  return (
    <form
      className="inline-form"
      onSubmit={(e) => {
        e.preventDefault()
        rename.mutate()
      }}
    >
      <label>
        Name shown in Stoke
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={cred.display_name} maxLength={100} autoFocus />
      </label>
      <button className="primary" disabled={rename.isPending}>Save</button>
      <button type="button" className="ghost" onClick={onDone}>Cancel</button>
      {rename.isError && <p className="error">{rename.error.message}</p>}
    </form>
  )
}

/** A password-type field for a Stripe key: not autocompleted, spellchecked or saved by the browser. */
function KeyInput({ value, onChange, autoFocus }: { value: string; onChange: (v: string) => void; autoFocus?: boolean }) {
  return (
    <input
      type="password"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="rk_live_…"
      autoComplete="off"
      spellCheck={false}
      autoCapitalize="off"
      autoCorrect="off"
      data-1p-ignore
      data-lpignore="true"
      maxLength={255}
      required
      autoFocus={autoFocus}
    />
  )
}

function ReplaceForm({ cred, onDone }: { cred: Credential; onDone: () => void }) {
  const invalidateAll = useInvalidateAll()
  const [key, setKey] = useState('')
  const replace = useMutation({
    mutationFn: (k: string) => api.replaceKey(cred.id, k),
    onSuccess: () => {
      invalidateAll()
      onDone()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    replace.mutate(key.trim())
    setKey('') // clear the field once sent
  }
  return (
    <form className="inline-form" onSubmit={submit}>
      <label>
        New key for {cred.label ?? cred.display_name}
        <KeyInput value={key} onChange={setKey} autoFocus />
      </label>
      <button className="primary" disabled={replace.isPending}>{replace.isPending ? 'Checking…' : 'Replace'}</button>
      <button type="button" className="ghost" onClick={onDone}>Cancel</button>
      {replace.isError && <p className="error">{replace.error.message}</p>}
    </form>
  )
}

function RemoveConfirm({ cred, onDone }: { cred: Credential; onDone: () => void }) {
  const invalidateAll = useInvalidateAll()
  const remove = useMutation({ mutationFn: () => api.deleteCredential(cred.id), onSuccess: invalidateAll })
  return (
    <div className="inline-form">
      <span>
        Remove {cred.label ?? cred.display_name}? Its customers will no longer appear in Stoke. The key is deleted from
        Stoke; to stop it working entirely, also delete it in your Stripe Dashboard.
      </span>
      <button className="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
        Remove
      </button>
      <button className="ghost" onClick={onDone}>Cancel</button>
      {remove.isError && <p className="error">{remove.error.message}</p>}
    </div>
  )
}

function AddCredential({ first }: { first: boolean }) {
  const invalidateAll = useInvalidateAll()
  const [key, setKey] = useState('')
  const [label, setLabel] = useState('')
  const add = useMutation({
    mutationFn: (v: { key: string; label: string }) => api.addCredential(v.key, v.label.trim()),
    onSuccess: () => {
      setLabel('')
      invalidateAll()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    add.mutate({ key: key.trim(), label })
    setKey('') // clear the field once sent
  }

  return (
    <form className="add-key card" onSubmit={submit}>
      <h3>{first ? 'Add your first Stripe account' : 'Add another Stripe account'}</h3>
      <ol className="muted steps">
        <li>
          In your Stripe Dashboard, open{' '}
          <a href="https://dashboard.stripe.com/apikeys" target="_blank" rel="noreferrer">
            Developers → API keys
          </a>{' '}
          and choose <strong>Create restricted key</strong>.
        </li>
        <li>Give it <strong>Read</strong> access to: {PERMISSIONS.join(', ')}. Leave everything else as None.</li>
        <li>Paste the key (it starts with rk_live_) below.</li>
      </ol>
      <div className="fields">
        <label>
          Restricted key
          <KeyInput value={key} onChange={setKey} />
        </label>
        <label>
          Name <span className="muted">(optional)</span>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. My newsletter" maxLength={100} />
        </label>
        <button className="primary" disabled={add.isPending}>{add.isPending ? 'Checking with Stripe…' : 'Add account'}</button>
      </div>
      {add.isError && <p className="error">{add.error.message}</p>}
      {add.isSuccess && (
        <p className="muted">
          Added {add.data.display_name}.
          {add.data.missing_permissions.length > 0 &&
            ` It can't read ${add.data.missing_permissions.join(', ')} yet: grant Read access in Stripe, then choose Re-check.`}
        </p>
      )}
    </form>
  )
}

function ReportingCurrency() {
  const invalidateAll = useInvalidateAll()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const save = useMutation({ mutationFn: api.saveSettings, onSuccess: invalidateAll })
  const current = settings.data?.reporting_currency ?? ''
  const options = current && !CURRENCIES.includes(current) ? [current, ...CURRENCIES] : CURRENCIES

  return (
    <section className="settings-section">
      <h2>Reporting currency</h2>
      <p className="muted lede-small">Every amount is converted to this currency.</p>
      <select
        aria-label="Reporting currency"
        value={current}
        disabled={!settings.isSuccess || save.isPending}
        onChange={(e) => save.mutate({ reporting_currency: e.target.value || null })}
      >
        <option value="">Automatic (first account's payout currency)</option>
        {options.map((c) => (
          <option key={c} value={c}>
            {c.toUpperCase()}
          </option>
        ))}
      </select>
      {save.isError && <p className="error">{save.error.message}</p>}
    </section>
  )
}
