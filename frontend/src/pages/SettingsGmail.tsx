import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api } from '../api'
import { Chip } from '../components/Chip'
import { formatRelative } from '../format'

// How connecting went, from ?gmail= on Google's way back through the API (routers/gmail.py).
const OUTCOMES: Record<string, { ok: boolean; message: string }> = {
  connected: { ok: true, message: 'Gmail connected.' },
  denied: { ok: false, message: 'Gmail wasn’t connected: you cancelled at Google.' },
  no_permission: {
    ok: false,
    message: 'Stoke needs permission to send email. Connect again and leave “Send email on your behalf” ticked.',
  },
  expired: { ok: false, message: 'That Gmail sign-in took too long. Try connecting again.' },
  invalid: { ok: false, message: 'That Gmail sign-in couldn’t be checked. Try connecting again from this browser.' },
  failed: { ok: false, message: 'Google didn’t accept that sign-in. Try connecting again.' },
}

/** The outcome Google's return left in the URL, shown once: the parameter is then removed. */
function useOutcome() {
  const [params, setParams] = useSearchParams()
  const [outcome] = useState(() => {
    const value = params.get('gmail')
    return value ? (OUTCOMES[value] ?? OUTCOMES.failed) : null
  })
  useEffect(() => {
    if (!params.has('gmail')) return
    params.delete('gmail')
    setParams(params, { replace: true, preventScrollReset: true })
  }, [params, setParams])
  return outcome
}

export function useGmail() {
  return useQuery({ queryKey: ['gmail'], queryFn: api.gmail })
}

/** Sends the writer to Google's consent page; they come back through the API to Settings. */
function useConnectGmail() {
  return useMutation({
    mutationFn: api.connectGmail,
    onSuccess: ({ url }) => window.location.assign(url),
  })
}

/** Settings: connect the Gmail that notes are sent from. */
export function GmailSettings() {
  const gmail = useGmail()
  const connect = useConnectGmail()
  const queryClient = useQueryClient()
  const disconnect = useMutation({
    mutationFn: api.disconnectGmail,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gmail'] }),
  })
  const g = gmail.data
  const outcome = useOutcome()

  return (
    <section className="settings-section">
      <h2 id="gmail">Gmail</h2>
      <p className="muted lede-small">
        Connect your Gmail so Stoke can send your approved notes from it. Notes land in your Sent folder and replies come
        to you. Stoke can only send: it can’t read, search or delete your email.
      </p>
      {outcome && <p className={outcome.ok ? 'muted' : 'error'}>{outcome.message}</p>}
      {gmail.isError && <p className="error">{gmail.error.message}</p>}
      {g && !g.available && <p className="muted">Gmail sending isn’t set up on this server yet.</p>}
      {g?.available && !g.email && (
        <button className="primary" disabled={connect.isPending} onClick={() => connect.mutate()}>
          {connect.isPending ? 'Opening Google…' : 'Connect Gmail'}
        </button>
      )}
      {g?.available && g.email && (
        <div className="gmail-connected">
          <div>
            <strong>{g.email}</strong>{' '}
            {g.status === 'ok' ? <Chip tone="ok">Connected</Chip> : <Chip tone="bad">Needs reconnecting</Chip>}
            <div className="muted small">
              {g.status === 'revoked'
                ? 'Google stopped letting Stoke send from this address. Reconnect to keep sending.'
                : g.last_sent_at
                  ? `Last sent ${formatRelative(g.last_sent_at)}`
                  : `Connected ${formatRelative(g.connected_at!)}`}
            </div>
          </div>
          <div className="form-buttons">
            <button className={g.status === 'ok' ? 'ghost' : 'primary'} disabled={connect.isPending} onClick={() => connect.mutate()}>
              {g.status === 'ok' ? 'Use a different Gmail' : 'Reconnect'}
            </button>
            <button className="link danger" disabled={disconnect.isPending} onClick={() => disconnect.mutate()}>
              Disconnect
            </button>
          </div>
        </div>
      )}
      {connect.isError && <p className="error">{connect.error.message}</p>}
      {disconnect.isError && <p className="error">{disconnect.error.message}</p>}
    </section>
  )
}

/** Shown where sending needs Gmail and it isn't connected. */
export function ConnectGmailHint({ action }: { action: string }) {
  return (
    <p className="muted small">
      <Link to="/settings#gmail">Connect your Gmail</Link> to {action}.
    </p>
  )
}
