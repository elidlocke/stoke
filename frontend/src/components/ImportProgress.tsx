import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Link } from 'react-router'
import { api, type SyncedObject } from '../api'
import { Chip } from './Chip'

const ORDER: SyncedObject[] = ['payment_intent', 'subscription', 'invoice', 'customer']
const NOUNS: Record<SyncedObject, string> = {
  payment_intent: 'payments',
  subscription: 'subscriptions',
  invoice: 'invoices',
  customer: 'customers',
}

/** Shown in place of the views while an account's Stripe history is first imported. Calls `onDone`
 *  once every account is ready, so the views load. */
export function ImportProgress({ onDone }: { onDone: () => void }) {
  const status = useQuery({ queryKey: ['sync-status'], queryFn: api.syncStatus, refetchInterval: 3000, staleTime: 0 })
  const accounts = status.data?.accounts ?? []
  const done = status.isSuccess && accounts.every((a) => a.state === 'ready')
  useEffect(() => {
    if (done) onDone()
  }, [done, onDone])

  return (
    <section className="import-progress card">
      <h1>Importing your Stripe history</h1>
      <p className="muted">
        Stoke is copying your payments and subscriptions from Stripe. For an account with years of history this
        takes a few minutes. Your dashboard opens here when it's done.
      </p>
      {status.isError && <p className="error">{status.error.message}</p>}
      <ul>
        {accounts.map((a) => {
          const counts = ORDER.flatMap((kind) =>
            a.objects
              .filter((o) => o.object === kind && o.state !== 'skipped')
              .map((o) => `${o.count.toLocaleString()} ${NOUNS[kind]}`),
          )
          return (
            <li key={a.id}>
              <div>
                <strong>{a.display_name}</strong>{' '}
                {a.state === 'ready' && <Chip tone="ok">Done</Chip>}
                {a.state === 'failed' && <Chip tone="bad">Import failed</Chip>}
              </div>
              <div className="muted small">
                {counts.length ? `${counts.join(', ')} so far` : 'Starting…'}
                {a.state === 'failed' && (
                  <>
                    {' · '}
                    <Link to="/settings">Retry in Settings</Link>
                  </>
                )}
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
