import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, type SubstackList } from '../api'
import { Cta } from '../components/Cta'
import { ItemStatus, ListBox, ListItem } from '../components/ListBox'
import { formatDate, formatRelative } from '../format'

function useSubstack() {
  return useQuery({ queryKey: ['substack'], queryFn: api.substack })
}

/** A publication's dashboard page on Substack. */
function dashboard(subdomain: string, page: 'home' | 'subscribers') {
  return `https://${subdomain}.substack.com/publish/${page}`
}

/** The writer's Substack handle: Stoke reads their public profile for their publications and the links on it. */
export function SubstackProfile() {
  const queryClient = useQueryClient()
  const substack = useSubstack()
  const [editing, setEditing] = useState(false)
  const [handle, setHandle] = useState('')
  const save = useMutation({
    mutationFn: api.setSubstackHandle,
    onSuccess: (data) => {
      queryClient.setQueryData(['substack'], data)
      setEditing(false)
    },
  })
  const s = substack.data
  const showForm = s && (s.handle === null || editing)

  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate(handle.trim() || null)
  }

  return (
    <section className="settings-section full">
      <h2 id="substack">Your Substack</h2>
      <p className="muted lede-small">
        Stoke pulls your publications, social links and anything you sell from your public profile, so you don’t have
        to type them in.
      </p>
      {substack.isError && <p className="error">{substack.error.message}</p>}
      {showForm && (
        <form className="card form-grid" onSubmit={submit}>
          <label className="half">
            Substack handle
            <input
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="@yourname"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              maxLength={200}
              required={s.handle === null}
              autoFocus={editing}
            />
          </label>
          <div className="form-buttons half">
            {editing ? (
              <button className="primary" disabled={save.isPending}>
                {save.isPending ? 'Reading your profile…' : 'Save'}
              </button>
            ) : (
              <Cta type="submit" disabled={save.isPending}>
                {save.isPending ? 'Reading your profile…' : 'Add your Substack'}
              </Cta>
            )}
            {editing && (
              <button type="button" className="ghost" onClick={() => setEditing(false)}>
                Cancel
              </button>
            )}
          </div>
          {save.isError && <p className="error full">{save.error.message}</p>}
        </form>
      )}
      {s?.handle && !editing && (
        <ListBox>
          <ListItem
            lead={s.profile?.photo_url && <img src={s.profile.photo_url} alt="" className="avatar" />}
            title={<strong>{s.profile?.name ?? `@${s.handle}`}</strong>}
            meta={
              <a href={s.profile?.url ?? `https://substack.com/@${s.handle}`} target="_blank" rel="noreferrer">
                substack.com/@{s.handle}
              </a>
            }
            status={
              s.error ? (
                <ItemStatus tone="warn" label="Couldn’t read profile" detail={s.error} />
              ) : (
                <ItemStatus
                  tone="ok"
                  label="Connected"
                  detail={`${s.publications.length} publication${s.publications.length === 1 ? '' : 's'}`}
                />
              )
            }
            actions={
              <button
                className="link"
                onClick={() => {
                  setHandle(`@${s.handle}`)
                  setEditing(true)
                }}
              >
                Change
              </button>
            }
          />
          {s.publications.map((p, i) => (
            <ListItem
              key={p.subdomain}
              title={p.name ?? p.subdomain}
              meta={
                <a href={p.url} target="_blank" rel="noreferrer">
                  {p.url.replace(/^https:\/\//, '')}
                </a>
              }
              status={<ItemStatus label={i === 0 ? 'Primary publication' : 'Publication'} />}
              actions={
                <a href={dashboard(p.subdomain, 'home')} target="_blank" rel="noreferrer">
                  Dashboard ↗
                </a>
              }
            />
          ))}
        </ListBox>
      )}
    </section>
  )
}

// An export this old is flagged: new readers are missing and engagement has moved on.
const STALE = 30 * 86400

export function isStale(exportedAt: number) {
  return Date.now() / 1000 - exportedAt > STALE
}

/** Every list change moves who's in the Free → paid action. */
function useInvalidateLists() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all(['substack-lists', 'actions', 'action'].map((k) => queryClient.invalidateQueries({ queryKey: [k] })))
}

/** The writer's free subscribers, uploaded from each publication's Substack export, for the Free → paid action. */
export function FreeSubscribers() {
  const substack = useSubstack()
  const lists = useQuery({ queryKey: ['substack-lists'], queryFn: api.substackLists })
  const publications = substack.data?.publications ?? []
  const uploaded = lists.data ?? []
  // A list stays listed after its publication leaves the profile, so it can still be removed.
  const gone = uploaded.filter((l) => !publications.some((p) => p.subdomain === l.publication))
  const items = [
    ...publications.map((p) => ({ subdomain: p.subdomain, name: p.name, list: uploaded.find((l) => l.publication === p.subdomain) })),
    ...gone.map((l) => ({ subdomain: l.publication, name: null, list: l })),
  ]

  return (
    <section className="settings-section full">
      <h2 id="free-subscribers">Your free subscribers</h2>
      <p className="muted lede-small">
        Stripe only knows who pays. Upload your free subscribers from Substack, and Stoke ranks them by how likely they are
        to upgrade, for the <Link to="/actions/free-to-paid">Free → paid</Link> action.
      </p>
      {lists.isError && <p className="error">{lists.error.message}</p>}
      <ol className="steps">
        <li>Open a publication’s subscribers in Substack, from its link below.</li>
        <li>
          Click the <strong>⋯</strong> (three dots) menu and choose <strong>Export</strong>. Substack downloads a CSV file.
        </li>
        <li>Upload that file next to the publication.</li>
      </ol>
      {items.length > 0 ? (
        <ListBox head="Publication">
          {items.map((item) => (
            <FreeListItem key={item.subdomain} {...item} />
          ))}
        </ListBox>
      ) : (
        substack.isSuccess &&
        lists.isSuccess && (
          <div className="section-cta">
            <a href="#substack" className="button primary cta">
              Add your Substack
            </a>
            <p className="muted small">Stoke needs your publications before you can upload their subscribers.</p>
          </div>
        )
      )}
      <p className="muted small">
        Stoke keeps only your free subscribers’ email, first name, start date and engagement counts, with emails and names
        encrypted. The file itself isn’t kept. Each upload replaces that publication’s last.
      </p>
    </section>
  )
}

function FreeListItem({ subdomain, name, list }: { subdomain: string; name: string | null; list?: SubstackList }) {
  const refresh = useInvalidateLists()
  const [removing, setRemoving] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const upload = useMutation({
    mutationFn: async (file: File) => api.uploadSubstackList(subdomain, { filename: file.name, csv: await file.text() }),
    onSuccess: refresh,
    onSettled: () => {
      if (input.current) input.current.value = ''
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteSubstackList(subdomain),
    onSuccess: () => {
      setRemoving(false)
      refresh()
    },
  })
  const stale = list ? isStale(list.exported_at) : false

  function choose(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) upload.mutate(file)
  }

  return (
    <ListItem
      title={name ?? subdomain}
      meta={
        <a href={dashboard(subdomain, 'subscribers')} target="_blank" rel="noreferrer">
          Subscribers in Substack ↗
        </a>
      }
      status={
        <ItemStatus
          tone={!list ? 'neutral' : stale ? 'warn' : 'ok'}
          label={!list ? 'Not uploaded' : stale ? 'Out of date' : 'Uploaded'}
          detail={
            <>
              {list && (
                <div>
                  {list.free_count.toLocaleString()} free subscriber{list.free_count === 1 ? '' : 's'} · exported{' '}
                  {formatDate(list.exported_at)} ({formatRelative(list.exported_at)})
                </div>
              )}
              {stale && <div>Upload a fresh export so new readers are included and engagement is current.</div>}
              {upload.isError && <div className="error">{upload.error.message}</div>}
            </>
          }
        />
      }
      actions={
        <>
          {/* Solid while there's something to fix; outlined once the list is current. */}
          <Cta small outline={!!list && !stale} onClick={() => input.current?.click()} disabled={upload.isPending}>
            {upload.isPending ? 'Uploading…' : list ? 'Upload newer' : 'Upload export'}
          </Cta>
          <input ref={input} type="file" accept=".csv,text/csv" onChange={choose} hidden />
          {list && (
            <button className="link danger" onClick={() => setRemoving(!removing)}>
              Remove
            </button>
          )}
        </>
      }
      expanded={
        removing && (
          <div className="inline-form">
            <span>Remove {name ?? subdomain}’s free subscribers from Stoke?</span>
            <button className="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
              Remove
            </button>
            <button className="ghost" onClick={() => setRemoving(false)}>
              Cancel
            </button>
            {remove.isError && <p className="error">{remove.error.message}</p>}
          </div>
        )
      }
    />
  )
}
