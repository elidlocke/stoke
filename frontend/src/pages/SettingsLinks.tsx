import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import {
  api,
  type Credential,
  type LinkCategory,
  type LinkSuggestion,
  type PaymentSource,
  type Purchase,
  type WriterLink,
  type WriterLinkIn,
} from '../api'
import { Chip } from '../components/Chip'
import { formatRelative } from '../format'
import { useAccountNames } from '../useAccounts'
import { kindLabel, LINK_KINDS, normalizeUrl, PURCHASES } from '../linkKinds'
import { useInvalidateLabels } from './SettingsProfile'

const NEWSLETTER = 'newsletter'
const OTHER = 'other'
const NEW_STREAM = '__new'

const SECTIONS: Record<LinkCategory, { title: string; lede: string; add: string; kindLabel: string }> = {
  revenue_source: {
    title: 'Revenue streams',
    lede:
      'Add what else you sell so Stoke can suggest who’d buy it, and skip those who already have.',
    add: 'Add a revenue stream',
    kindLabel: 'Platform',
  },
  social: {
    title: 'Audience channels',
    lede:
      'Add where else readers can follow you so Stoke can include these links in your notes, like the Welcome note.',
    add: 'Add a channel',
    kindLabel: 'Type',
  },
}

export function RevenueStreams() {
  return <LinkSection category="revenue_source" />
}

export function AudienceChannels() {
  return <LinkSection category="social" />
}

/** Substack links stay saved (notes' {{substack}} reads them) but aren't listed: the writer's Substack
 *  is its own section at the top of Settings. */
function shown(l: { category: LinkCategory; kind: string }): boolean {
  return !(l.category === 'social' && l.kind === 'substack')
}

/** The id a connected account's links refer to: its Stripe id, or for a key that can't read it, the
 *  key's own (credential_account_id in backend/app/db_models.py). */
function accountId(c: Credential): string {
  return c.stripe_account_id ?? `key-${c.id}`
}

function useAccounts(): Credential[] {
  return useQuery({ queryKey: ['credentials'], queryFn: api.credentials }).data?.credentials ?? []
}

/** A link added, changed or removed: the suggestions and payment platforms' guesses follow the links. */
function useInvalidateLinks() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all(
      ['links', 'substack', 'payment-sources'].map((k) => queryClient.invalidateQueries({ queryKey: [k] })),
    )
}

function usePaymentSources(enabled: boolean): PaymentSource[] {
  return useQuery({ queryKey: ['payment-sources'], queryFn: api.paymentSources, enabled }).data?.sources ?? []
}

function LinkSection({ category }: { category: LinkCategory }) {
  const links = useQuery({ queryKey: ['links'], queryFn: api.links })
  const [adding, setAdding] = useState(false)
  const list = links.data?.links.filter((l) => l.category === category && shown(l)) ?? []
  const copy = SECTIONS[category]
  const isRevenue = category === 'revenue_source'
  const sources = usePaymentSources(isRevenue)
  // Channels found on the Substack profile are listed with the saved ones, to confirm like a plan's label.
  const substack = useQuery({ queryKey: ['substack'], queryFn: api.substack, enabled: !isRevenue })
  const guesses = isRevenue ? [] : (substack.data?.suggestions.filter((s) => s.category === 'social' && shown(s)) ?? [])

  return (
    <section className="settings-section full">
      <h2 id={isRevenue ? 'revenue' : 'channels'}>{copy.title}</h2>
      <p className="muted lede-small">{copy.lede}</p>
      {links.isError && <p className="error">{links.error.message}</p>}
      {isRevenue && <PaymentsFound sources={sources.filter((s) => s.label === null)} streams={list} />}
      {isRevenue && <Suggestions category={category} />}
      {guesses.length > 1 && <ConfirmAll guesses={guesses} />}
      {(list.length > 0 || guesses.length > 0) && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{isRevenue ? 'Name' : copy.kindLabel}</th>
                <th>Link</th>
                {isRevenue && <th>Paid through</th>}
                {isRevenue && <th>Payment</th>}
                {isRevenue && <th>Sales recorded by</th>}
                {!isRevenue && <th />}
                <th className="right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {list.map((l) => (
                <LinkRow key={l.id} link={l} platforms={sources.filter((s) => s.label === l.id)} />
              ))}
              {guesses.map((s) => (
                <GuessedChannelRow key={s.url} guess={s} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {isRevenue && <OtherPlatforms sources={sources.filter((s) => s.label === NEWSLETTER || s.label === OTHER)} />}
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

// ---- Suggestions from the writer's Substack profile ----

function suggestionBody(s: LinkSuggestion): WriterLinkIn {
  return { category: s.category, kind: s.kind, name: s.name, url: s.url, paid_via_account_id: null, purchase: s.purchase }
}

/** Revenue streams found on the Substack profile. Each needs how it's paid for, so it's reviewed before
 *  it's added. */
function Suggestions({ category }: { category: LinkCategory }) {
  const substack = useQuery({ queryKey: ['substack'], queryFn: api.substack })
  const [reviewing, setReviewing] = useState<string | null>(null) // a suggestion's url
  const list = substack.data?.suggestions.filter((s) => s.category === category && shown(s)) ?? []
  if (list.length === 0) return null

  return (
    <div className="suggestions">
      <div className="suggestions-header">
        <span className="muted small">Found on your Substack profile</span>
      </div>
      <div className="settings-grid">
        {list.map((s) =>
          reviewing === s.url ? (
            <AddLink key={s.url} category={category} initial={suggestionBody(s)} onDone={() => setReviewing(null)} />
          ) : (
            <div key={s.url} className="card suggestion half">
              <div className="suggestion-text">
                <strong>{s.name ?? kindLabel(s.category, s.kind)}</strong>
                <div className="muted small link-url">
                  {s.name && `${kindLabel(s.category, s.kind)} · `}
                  {s.url.replace(/^https:\/\//, '')}
                </div>
              </div>
              <button className="ghost" onClick={() => setReviewing(s.url)}>
                Review & add
              </button>
            </div>
          ),
        )}
      </div>
    </div>
  )
}

// ---- Platforms that take payments into the writer's Stripe accounts ----

function platformKind(platform: string | null): string {
  const name = (platform ?? '').toLowerCase()
  return Object.keys(LINK_KINDS.revenue_source).find((k) => k !== 'other' && name.includes(k)) ?? 'other'
}

/** Platforms whose payments aren't matched to a stream yet: the writer says what each one sells. */
function PaymentsFound({ sources, streams }: { sources: PaymentSource[]; streams: WriterLink[] }) {
  if (sources.length === 0) return null
  return (
    <div className="card payments-found">
      <h3>Payments Stoke found</h3>
      <p className="muted small">
        Match each platform to what it sells so Stoke knows who has already bought what.
      </p>
      <ul className="payments-found-list">
        {sources.map((s) => (
          <PaymentFoundRow key={s.id} source={s} streams={streams} />
        ))}
      </ul>
    </div>
  )
}

function PaymentFoundRow({ source: s, streams }: { source: PaymentSource; streams: WriterLink[] }) {
  const invalidate = useInvalidateLabels()
  const accountName = useAccountNames()
  const [creating, setCreating] = useState(false)
  const save = useMutation({
    mutationFn: (label: string | null) => api.labelPaymentSource(s.id, label),
    onSuccess: invalidate,
  })
  const shown = s.suggested ?? ''
  const kind = platformKind(s.platform)

  return (
    <li>
      <div className="payment-found">
        <div className="payment-found-text">
          <strong>{s.platform ?? 'Unnamed platform'}</strong>
          <div className="muted small">
            {s.payments} payment{s.payments === 1 ? '' : 's'} from {s.customers} customer{s.customers === 1 ? '' : 's'},
            last {formatRelative(s.last_paid)} · {s.account_ids.map(accountName).join(', ')}
            {s.example && <> · {s.example}</>}
          </div>
        </div>
        <select
            aria-label="What it sells"
            className="payment-found-select"
            value={creating ? NEW_STREAM : shown}
            disabled={save.isPending}
            onChange={(e) => {
              if (e.target.value === NEW_STREAM) return setCreating(true)
              setCreating(false)
              if (e.target.value) save.mutate(e.target.value)
            }}
          >
            {!shown && <option value="">What is this?</option>}
            <option value={NEWSLETTER}>Your newsletter</option>
            {streams.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
            <option value={OTHER}>Something else</option>
            <option value={NEW_STREAM}>+ New revenue stream</option>
          </select>
        {s.suggested !== null && !creating && (
          <span className="small">
            <Chip>Stoke’s guess</Chip>{' '}
            <button className="link" disabled={save.isPending} onClick={() => save.mutate(s.suggested)}>
              Confirm
            </button>
          </span>
        )}
      </div>
      {save.isError && <p className="error small">{save.error.message}</p>}
      {creating && (
        <AddLink
          category="revenue_source"
          initial={{
            category: 'revenue_source',
            kind,
            name: s.platform,
            url: '',
            paid_via_account_id: s.account_ids[0] ?? null,
            purchase: LINK_KINDS.revenue_source[kind].purchase ?? 'once',
          }}
          onAdded={(link) => save.mutate(link.id)}
          onDone={() => setCreating(false)}
        />
      )}
    </li>
  )
}

/** Platforms confirmed as the newsletter's own, or as something else: not a revenue stream. */
function OtherPlatforms({ sources }: { sources: PaymentSource[] }) {
  const invalidate = useInvalidateLabels()
  const reset = useMutation({ mutationFn: (id: string) => api.labelPaymentSource(id, null), onSuccess: invalidate })
  if (sources.length === 0) return null
  return (
    <p className="muted small other-platforms">
      {sources.map((s, i) => (
        <span key={s.id}>
          {i > 0 && ' · '}
          {s.platform ?? 'An unnamed platform'}’s payments are counted as{' '}
          {s.label === NEWSLETTER ? 'your newsletter' : 'something else'}{' '}
          <button className="link" disabled={reset.isPending} onClick={() => reset.mutate(s.id)}>
            Change
          </button>
        </span>
      ))}
      {reset.isError && <span className="error"> {reset.error.message}</span>}
    </p>
  )
}

// ---- The writer's links ----

function LinkRow({ link, platforms }: { link: WriterLink; platforms: PaymentSource[] }) {
  const invalidate = useInvalidateLinks()
  const invalidateLabels = useInvalidateLabels()
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
  const unlink = useMutation({ mutationFn: (id: string) => api.labelPaymentSource(id, null), onSuccess: invalidateLabels })
  const isRevenue = link.category === 'revenue_source'
  const account = accounts.find((c) => accountId(c) === link.paid_via_account_id)
  const columns = isRevenue ? 6 : 4

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
        {isRevenue && (
          <td className="wrap">
            {platforms.length === 0 ? (
              <span className="muted">—</span>
            ) : (
              platforms.map((p) => (
                <div key={p.id}>
                  {p.platform ?? 'Unnamed platform'}{' '}
                  <button className="link small" disabled={unlink.isPending} onClick={() => unlink.mutate(p.id)}>
                    Unlink
                  </button>
                </div>
              ))
            )}
            {unlink.isError && <div className="error small">{unlink.error.message}</div>}
          </td>
        )}
        {!isRevenue && (
          <td>
            <Chip tone="ok">Confirmed</Chip>
          </td>
        )}
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
                editing
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

/** A channel found on the writer's Substack profile: Stoke's guess, saved once confirmed. */
function GuessedChannelRow({ guess }: { guess: LinkSuggestion }) {
  const invalidate = useInvalidateLinks()
  const [editing, setEditing] = useState(false)
  const confirm = useMutation({ mutationFn: api.addLink, onSuccess: invalidate })
  return (
    <>
      <tr>
        <td className="wrap">
          {kindLabel(guess.category, guess.kind)}
          {guess.name && <div className="muted small">{guess.name}</div>}
        </td>
        <td className="wrap link-url">
          <a href={guess.url} target="_blank" rel="noreferrer">
            {guess.url.replace(/^https:\/\//, '')}
          </a>
        </td>
        <td>
          <Chip>Stoke’s guess</Chip>{' '}
          <button className="link" onClick={() => confirm.mutate(suggestionBody(guess))} disabled={confirm.isPending}>
            Confirm
          </button>
          {confirm.isError && !editing && <div className="error small">{confirm.error.message}</div>}
        </td>
        <td className="right actions">
          <button className="link" onClick={() => setEditing(!editing)}>
            Edit
          </button>
        </td>
      </tr>
      {editing && (
        <tr className="edit-row">
          <td colSpan={4}>
            <LinkForm
              category="social"
              initial={suggestionBody(guess)}
              submitLabel="Confirm"
              pending={confirm.isPending}
              error={confirm.error}
              onSubmit={(body) => confirm.mutate(body)}
              onCancel={() => setEditing(false)}
            />
          </td>
        </tr>
      )}
    </>
  )
}

function ConfirmAll({ guesses }: { guesses: LinkSuggestion[] }) {
  const invalidate = useInvalidateLinks()
  const confirm = useMutation({
    mutationFn: async () => {
      for (const s of guesses) await api.addLink(suggestionBody(s))
    },
    onSettled: invalidate,
  })
  return (
    <p className="small">
      <span className="muted">Stoke found {guesses.length} channels on your Substack profile.</span>{' '}
      <button className="link" onClick={() => confirm.mutate()} disabled={confirm.isPending}>
        Confirm all
      </button>
      {confirm.isError && <span className="error"> {confirm.error.message}</span>}
    </p>
  )
}

function AddLink({
  category,
  initial,
  onAdded,
  onDone,
}: {
  category: LinkCategory
  initial?: WriterLinkIn // prefilled, e.g. from a suggestion
  onAdded?: (link: WriterLink) => void
  onDone: () => void
}) {
  const invalidate = useInvalidateLinks()
  const add = useMutation({
    mutationFn: api.addLink,
    onSuccess: (link) => {
      invalidate()
      onAdded?.(link)
      onDone()
    },
  })
  return (
    <div className="card add-link full">
      <LinkForm
        category={category}
        initial={initial}
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
  editing = false,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  category: LinkCategory
  initial?: WriterLinkIn
  editing?: boolean // an existing link, rather than a new one (blank or prefilled)
  submitLabel: string
  pending: boolean
  error: Error | null
  onSubmit: (body: WriterLinkIn) => void
  onCancel: () => void
}) {
  const accounts = useAccounts()
  const kinds = LINK_KINDS[category]
  const isRevenue = category === 'revenue_source'
  const [kind, setKind] = useState(initial?.kind ?? Object.keys(kinds).find((k) => shown({ category, kind: k }))!)
  const [name, setName] = useState(initial?.name ?? '')
  const [url, setUrl] = useState(initial?.url ?? '')
  // A new revenue source is paid through the only account, if there's just one.
  const [paidVia, setPaidVia] = useState(
    editing || initial?.paid_via_account_id
      ? (initial?.paid_via_account_id ?? '')
      : accounts.length === 1
        ? accountId(accounts[0])
        : '',
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
    <form className="form-grid" onSubmit={submit}>
      <label className="half">
        {SECTIONS[category].kindLabel}
        <select value={kind} onChange={(e) => setKind(e.target.value)} autoFocus={!editing}>
          {Object.entries(kinds)
            .filter(([value]) => value === kind || shown({ category, kind: value }))
            .map(([value, k]) => (
              <option key={value} value={value}>
                {k.label}
              </option>
            ))}
        </select>
      </label>
      <label className="half">
        {isRevenue ? 'Name' : <>Label <span className="muted">(optional)</span></>}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={isRevenue ? 'e.g. 1:1 strategy call' : ''}
          maxLength={120}
          required={isRevenue}
        />
      </label>
      <label className="full">
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
        <label className="half">
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
        <label className="half">
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
      <div className="form-buttons full">
        <button className="primary" disabled={pending}>
          {submitLabel}
        </button>
        <button type="button" className="ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error && <p className="error full">{error.message}</p>}
    </form>
  )
}
