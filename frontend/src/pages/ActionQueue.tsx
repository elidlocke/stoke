import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api, type NotePart, type QueueEntry } from '../api'
import { Chip } from '../components/Chip'
import { Filled } from '../components/Filled'
import { ContactedChip } from '../components/ContactedChip'
import { Money } from '../components/Money'
import { formatDate, formatRelative } from '../format'
import { customerPath } from '../routes'
import { useInvalidateAction } from './ActionTemplate'
import { ConnectGmailHint, useGmail } from './SettingsGmail'

/** Everyone left to contact for the action, each with their note: copy or open it, then mark it sent or skip. */
export function Queue({ kind, account, currency }: { kind: string; account?: string; currency: string }) {
  const queue = useQuery({ queryKey: ['action-queue', kind, account], queryFn: () => api.queue(kind, account) })
  const gmail = useGmail()
  const canSend = gmail.data?.status === 'ok'
  if (queue.isPending) return <p className="muted">Filling in each note…</p>
  if (queue.isError) return <p className="error">{queue.error.message}</p>
  if (!queue.data.open)
    return <p className="muted">Turn this action on and approve its note template to open the queue.</p>
  if (queue.data.customers.length === 0) return <p className="muted">Everyone in this audience has been contacted or skipped.</p>
  return (
    <>
      <p className="muted">
        {queue.data.customers.length} to go, highest value first.{' '}
        {canSend
          ? `Send each note from ${gmail.data!.email}, or send it yourself and mark it sent.`
          : 'Send each note from your own email, then mark it sent.'}
      </p>
      {gmail.data?.available && !canSend && <ConnectGmailHint action="send these notes from Stoke" />}
      <div className="queue">
        {queue.data.customers.map((c) => (
          <NoteCard key={c.customer_id} kind={kind} entry={c} currency={currency} canSend={canSend} />
        ))}
      </div>
    </>
  )
}

function plain(parts: NotePart[]): string {
  return parts.map((p) => p.text).join('')
}

function NoteCard({
  kind,
  entry: c,
  currency,
  canSend,
}: {
  kind: string
  entry: QueueEntry
  currency: string
  canSend: boolean
}) {
  const invalidate = useInvalidateAction(kind)
  const [editing, setEditing] = useState(false)
  const [subject, setSubject] = useState(plain(c.note.subject))
  const [body, setBody] = useState(plain(c.note.body))
  const [copied, setCopied] = useState(false)
  const mark = useMutation({
    mutationFn: (status: 'sent' | 'skipped') => api.markOutreach(kind, { customer_id: c.customer_id, status, subject, body }),
    onSuccess: invalidate,
  })
  const [confirming, setConfirming] = useState(false)
  const send = useMutation({
    mutationFn: () => api.sendNote(kind, { customer_id: c.customer_id, subject, body }),
    onSuccess: invalidate,
    onSettled: () => setConfirming(false),
  })
  const busy = mark.isPending || send.isPending
  const edited = subject !== plain(c.note.subject) || body !== plain(c.note.body)
  const mailto = `mailto:${encodeURIComponent(c.email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`

  const copy = async () => {
    await navigator.clipboard.writeText(body)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <article className="card note-card">
      <header className="note-card-header">
        <div className="note-card-who">
          <Link to={customerPath(c.customer_id)}>{c.email}</Link> <ContactedChip customerId={c.customer_id} />
          <div className="muted small">
            {c.why}
            {c.plan && <> · {c.plan}</>} · <Money amount={c.lifetime_value} currency={currency} /> lifetime
          </div>
        </div>
        {c.deadline != null && (
          <span className="muted small">
            Act by {formatDate(c.deadline)} ({formatRelative(c.deadline)})
          </span>
        )}
      </header>

      {editing ? (
        <div className="note-edit">
          <input aria-label="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
          <textarea aria-label="Note" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
        </div>
      ) : edited ? (
        <div className="note">
          <div className="note-subject">{subject}</div>
          <div className="note-body">{body}</div>
        </div>
      ) : (
        <div className="note">
          <div className="note-subject">
            <Filled parts={c.note.subject} />
          </div>
          <div className="note-body">
            <Filled parts={c.note.body} />
          </div>
        </div>
      )}
      {c.note.missing.length > 0 && !edited && (
        <p className="warning small">
          No value for {c.note.missing.map((f) => `{{${f}}}`).join(', ')}. Add it in <Link to="/settings">Settings</Link>, or
          edit this note.
        </p>
      )}
      {mark.isError && <p className="error">{mark.error.message}</p>}
      {send.isError && <p className="error">{send.error.message}</p>}

      {confirming ? (
        <div className="form-buttons">
          <span>
            Send this to <strong>{c.email}</strong> from your Gmail now?
          </span>
          <button className="primary" disabled={busy || !subject.trim() || !body.trim()} onClick={() => send.mutate()}>
            {send.isPending ? 'Sending…' : 'Send'}
          </button>
          <button className="link" disabled={send.isPending} onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="form-buttons">
          {canSend && (
            <button className="primary" disabled={busy} onClick={() => setConfirming(true)}>
              Send from Gmail
            </button>
          )}
          <a className="button ghost" href={mailto}>
            Open in email
          </a>
          <button className="ghost" onClick={copy}>
            {copied ? 'Copied' : 'Copy note'}
          </button>
          <button className="ghost" onClick={() => setEditing(!editing)}>
            {editing ? 'Done editing' : 'Edit'}
          </button>
          <button className={canSend ? 'ghost' : 'primary'} disabled={busy} onClick={() => mark.mutate('sent')}>
            Mark sent
          </button>
          <button className="link" disabled={busy} onClick={() => mark.mutate('skipped')}>
            Skip
          </button>
        </div>
      )}
    </article>
  )
}

/** Everyone marked sent or skipped for the action; undo puts them back in the queue. */
export function History({ kind }: { kind: string }) {
  const history = useQuery({ queryKey: ['action-history', kind], queryFn: () => api.actionOutreach(kind) })
  const invalidate = useInvalidateAction(kind)
  const undo = useMutation({ mutationFn: (id: string) => api.deleteOutreach(id), onSuccess: invalidate })
  if (history.isPending) return <p className="muted">Loading…</p>
  if (history.isError) return <p className="error">{history.error.message}</p>
  if (history.data.outreach.length === 0) return <p className="muted">No one contacted or skipped yet.</p>
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Customer</th>
            <th>Status</th>
            <th>When</th>
            <th>Subject</th>
            <th className="right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {history.data.outreach.map((o) => (
            <tr key={o.id}>
              <td>
                {o.email ? (
                  <Link to={customerPath(o.customer_id)}>{o.email}</Link>
                ) : (
                  <span className="muted">No longer in your Stripe data</span>
                )}
              </td>
              <td>
                {o.status === 'sent' ? (
                  <Chip tone="ok" title={o.via_gmail ? 'Sent by Stoke from your Gmail' : 'You sent it and marked it sent'}>
                    {o.via_gmail ? 'Sent from Gmail' : 'Sent'}
                  </Chip>
                ) : (
                  <Chip>Skipped</Chip>
                )}
              </td>
              <td>{formatDate(o.sent_at ?? o.created_at)}</td>
              <td className="wrap" title={o.body}>
                {o.subject || <span className="muted">—</span>}
              </td>
              <td className="right">
                <button className="link" disabled={undo.isPending} onClick={() => undo.mutate(o.id)}>
                  Undo
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
