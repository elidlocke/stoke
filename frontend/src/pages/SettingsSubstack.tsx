import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { Chip } from '../components/Chip'

/** The writer's Substack handle: Stoke reads their public profile for the links on it. */
export function SubstackProfile() {
  const queryClient = useQueryClient()
  const substack = useQuery({ queryKey: ['substack'], queryFn: api.substack })
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
      <h2 id="substack">
        1 · Your Substack {s?.handle && <Chip tone="ok">Connected</Chip>}
      </h2>
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
            <button className="primary" disabled={save.isPending}>
              {save.isPending ? 'Reading your profile…' : 'Save'}
            </button>
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
        <div className="card substack-profile">
          {s.profile?.photo_url && <img src={s.profile.photo_url} alt="" className="avatar" />}
          <div>
            <strong>{s.profile?.name ?? `@${s.handle}`}</strong>
            <div className="muted small">
              <a href={s.profile?.url ?? `https://substack.com/@${s.handle}`} target="_blank" rel="noreferrer">
                substack.com/@{s.handle}
              </a>
            </div>
          </div>
          <button
            className="link"
            onClick={() => {
              setHandle(`@${s.handle}`)
              setEditing(true)
            }}
          >
            Change
          </button>
        </div>
      )}
      {s?.error && !editing && <p className="muted small">{s.error}</p>}
    </section>
  )
}
