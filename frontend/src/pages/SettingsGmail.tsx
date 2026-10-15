import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../api'
import { Cta } from '../components/Cta'
import { ItemStatus, ListBox, ListItem } from '../components/ListBox'
import { formatRelative } from '../format'
import { useOAuthOutcome, type Outcome } from '../useOAuthOutcome'

// How connecting went, from ?gmail= on Google's way back through the API (routers/gmail.py).
const OUTCOMES: Record<string, Outcome> = {
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
  const outcome = useOAuthOutcome('gmail', OUTCOMES, 'failed')

  return (
    <section className="settings-section full">
      <h2 id="gmail">Gmail</h2>
      <p className="muted lede-small">
        Connect Gmail when you’re ready to send. Notes go from your address and replies come to you; Stoke can’t read
        your email.
      </p>
      {outcome && <p className={outcome.ok ? 'muted' : 'error'}>{outcome.message}</p>}
      {gmail.isError && <p className="error">{gmail.error.message}</p>}
      {g && !g.available && <p className="muted">Gmail sending isn’t set up on this server yet.</p>}
      {g?.available && !g.email && (
        <Cta disabled={connect.isPending} onClick={() => connect.mutate()}>
          {connect.isPending ? 'Opening Google…' : 'Connect Gmail'}
        </Cta>
      )}
      {g?.available && g.email && (
        <ListBox head="Account">
          <ListItem
            title={g.email}
            status={
              <ItemStatus
                tone={g.status === 'ok' ? 'ok' : 'bad'}
                label={g.status === 'ok' ? 'Connected' : 'Needs reconnecting'}
                detail={
                  g.status === 'revoked'
                    ? 'Google stopped letting Stoke send from this address. Reconnect to keep sending.'
                    : g.last_sent_at
                      ? `Last sent ${formatRelative(g.last_sent_at)}`
                      : `Connected ${formatRelative(g.connected_at!)}`
                }
              />
            }
            actions={
              <>
                <button className="link" disabled={connect.isPending} onClick={() => connect.mutate()}>
                  {g.status === 'ok' ? 'Use a different Gmail' : 'Reconnect'}
                </button>
                <button className="link danger" disabled={disconnect.isPending} onClick={() => disconnect.mutate()}>
                  Disconnect
                </button>
              </>
            }
          />
        </ListBox>
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
