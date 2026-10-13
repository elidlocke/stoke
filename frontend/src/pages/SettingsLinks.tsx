import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, type Credential, type LinkCategory, type Purchase, type WriterLink, type WriterLinkIn } from '../api'
import { kindLabel, LINK_KINDS, normalizeUrl, PURCHASES } from '../linkKinds'

const SECTIONS: Record<LinkCategory, { title: string; lede: string; add: string; kindLabel: string }> = {
  revenue_source: {
    title: 'Revenue streams',
    lede:
      'Where else readers can pay you: calls on Calendly, courses on Maven or Teachable, downloads on Gumroad, a ' +
      'community on Circle, events on Luma. Stoke uses these to suggest which of your readers would buy each one, ' +
      "and when it's paid through one of your Stripe accounts, to skip the people who already have.",
    add: 'Add a revenue stream',
    kindLabel: 'Platform',
  },
  social: {
    title: 'Audience channels',
    lede:
      'Where else readers can follow you: your Substack, socials, podcast or website. Stoke uses these to invite ' +
      'your paying readers to follow you on more channels, so they see more of your work and stay longer.',
    add: 'Add a channel',
    kindLabel: 'Type',
  },
}

export function WriterLinks() {
  return (
    <>
      <LinkSection category="revenue_source" />
      <LinkSection category="social" />
    </>
  )
}

/** The id a connected account's links refer to: its Stripe id, or for a key that can't read it, the
 *  key's own (credential_account_id in backend/app/db_models.py). */
function accountId(c: Credential): string {
  return c.stripe_account_id ?? `key-${c.id}`
}

function useAccounts(): Credential[] {
  return useQuery({ queryKey: ['credentials'], queryFn: api.credentials }).data?.credentials ?? []
}

function useInvalidateLinks() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['links'] })
}

function LinkSection({ category }: { category: LinkCategory }) {
  const links = useQuery({ queryKey: ['links'], queryFn: api.links })
  const [adding, setAdding] = useState(false)
  const list = links.data?.links.filter((l) => l.category === category) ?? []
  const copy = SECTIONS[category]
  const isRevenue = category === 'revenue_source'

  return (
    <section className="settings-section">
      <h2>{copy.title}</h2>
      <p className="muted lede-small">{copy.lede}</p>
      {links.isError && <p className="error">{links.error.message}</p>}
      {list.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{isRevenue ? 'Name' : copy.kindLabel}</th>
                <th>Link</th>
                {isRevenue && <th>Paid through</th>}
                {isRevenue && <th>Payment</th>}
                <th className="right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {list.map((l) => (
                <LinkRow key={l.id} link={l} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {links.isSuccess &&
        (adding ? (
          <AddLink category={category} onDone={() => setAdding(false)} />
        ) : (
          <button className="ghost add-link" onClick={() => setAdding(true)}>
            {copy.add}
          </button>
        ))}
    </section>
  )
}

function LinkRow({ link }: { link: WriterLink }) {
  const invalidate = useInvalidateLinks()
  const accounts = useAccounts()
  const [editing, setEditing] = useState<'edit' | 'remove' | null>(null)
  const update = useMutation({
    mutationFn: (body: WriterLinkIn) => api.updateLink(link.id, body),
    onSuccess: () => {
      invalidate()
      setEditing(null)
    },
  })
  const remove = useMutation({ mutationFn: () => api.deleteLink(link.id), onSuccess: invalidate })
  const isRevenue = link.category === 'revenue_source'
  const account = accounts.find((c) => accountId(c) === link.paid_via_account_id)
  const columns = isRevenue ? 5 : 3

  return (
    <>
      <tr>
        <td className="wrap">
          {isRevenue ? link.name : kindLabel(link.category, link.kind)}
          {(isRevenue || link.name) && (
            <div className="muted small">{isRevenue ? kindLabel(link.category, link.kind) : link.name}</div>
          )}
        </td>
        <td className="wrap link-url">
          <a href={link.url} target="_blank" rel="noreferrer">
            {link.url.replace(/^https:\/\//, '')}
          </a>
        </td>
        {isRevenue && (
          <td className="wrap">
            {link.paid_via_account_id === null ? (
              <span className="muted">Somewhere else</span>
            ) : account ? (
              account.label ?? account.display_name
            ) : (
              <span className="muted">A removed account</span>
            )}
          </td>
        )}
        {isRevenue && <td>{PURCHASES.find((p) => p.value === link.purchase)?.label}</td>}
        <td className="right actions">
          <button className="link" onClick={() => setEditing(editing === 'edit' ? null : 'edit')}>
            Edit
          </button>
          <button className="link danger" onClick={() => setEditing(editing === 'remove' ? null : 'remove')}>
            Remove
          </button>
        </td>
      </tr>
      {editing && (
        <tr className="edit-row">
          <td colSpan={columns}>
            {editing === 'edit' ? (
              <LinkForm
                category={link.category}
                initial={link}
                submitLabel="Save"
                pending={update.isPending}
                error={update.error}
                onSubmit={(body) => update.mutate(body)}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <div className="inline-form">
                <span>Remove {link.name ?? kindLabel(link.category, link.kind)}?</span>
                <button className="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
                  Remove
                </button>
                <button className="ghost" onClick={() => setEditing(null)}>
                  Cancel
                </button>
                {remove.isError && <p className="error">{remove.error.message}</p>}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

function AddLink({ category, onDone }: { category: LinkCategory; onDone: () => void }) {
  const invalidate = useInvalidateLinks()
  const add = useMutation({
    mutationFn: api.addLink,
    onSuccess: () => {
      invalidate()
      onDone()
    },
  })
  return (
    <div className="card add-link">
      <LinkForm
        category={category}
        submitLabel="Add"
        pending={add.isPending}
        error={add.error}
        onSubmit={(body) => add.mutate(body)}
        onCancel={onDone}
      />
    </div>
  )
}

function LinkForm({
  category,
  initial,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  category: LinkCategory
  initial?: WriterLink
  submitLabel: string
  pending: boolean
  error: Error | null
  onSubmit: (body: WriterLinkIn) => void
  onCancel: () => void
}) {
  const accounts = useAccounts()
  const kinds = LINK_KINDS[category]
  const isRevenue = category === 'revenue_source'
  const [kind, setKind] = useState(initial?.kind ?? Object.keys(kinds)[0])
  const [name, setName] = useState(initial?.name ?? '')
  const [url, setUrl] = useState(initial?.url ?? '')
  // A new revenue source is paid through the only account, if there's just one.
  const [paidVia, setPaidVia] = useState(
    initial ? (initial.paid_via_account_id ?? '') : accounts.length === 1 ? accountId(accounts[0]) : '',
  )
  const [purchase, setPurchase] = useState<Purchase | null>(initial?.purchase ?? null)

  function submit(e: FormEvent) {
    e.preventDefault()
    onSubmit({
      category,
      kind,
      name: name.trim() || null,
      url: normalizeUrl(url),
      paid_via_account_id: isRevenue ? paidVia || null : null,
      // Until chosen, follows the platform: changing Calendly to Maven changes "repeat" to "once".
      purchase: isRevenue ? (purchase ?? kinds[kind].purchase ?? 'once') : null,
    })
  }

  return (
    <form className="inline-form link-form" onSubmit={submit}>
      <label>
        {SECTIONS[category].kindLabel}
        <select value={kind} onChange={(e) => setKind(e.target.value)} autoFocus={!initial}>
          {Object.entries(kinds).map(([value, k]) => (
            <option key={value} value={value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        {isRevenue ? 'Name' : <>Label <span className="muted">(optional)</span></>}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={isRevenue ? 'e.g. 1:1 strategy call' : ''}
          maxLength={120}
          required={isRevenue}
        />
      </label>
      <label className="wide">
        Link
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={kinds[kind].placeholder}
          inputMode="url"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          maxLength={2000}
          pattern="\s*(https?:\/\/)?\S+\.\S+\s*"
          title="A link like calendly.com/you"
          required
        />
      </label>
      {isRevenue && (
        <label>
          Paid through
          <select value={paidVia} onChange={(e) => setPaidVia(e.target.value)}>
            {accounts.map((c) => (
              <option key={c.id} value={accountId(c)}>
                {c.label ?? c.display_name}
              </option>
            ))}
            <option value="">Somewhere else (Stoke can't see these sales)</option>
          </select>
        </label>
      )}
      {isRevenue && (
        <label>
          How do people pay?
          <select
            value={purchase ?? kinds[kind].purchase ?? 'once'}
            onChange={(e) => setPurchase(e.target.value as Purchase)}
          >
            {PURCHASES.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="form-buttons">
        <button className="primary" disabled={pending}>
          {submitLabel}
        </button>
        <button type="button" className="ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error && <p className="error">{error.message}</p>}
    </form>
  )
}
