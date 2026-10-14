import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Plan, type PlanLabel } from '../api'
import { Confirmation } from '../components/Confirmation'
import { Money } from '../components/Money'
import { useAccountNames, useMultipleAccounts } from '../useAccounts'

const PLAN_LABELS: { value: PlanLabel; label: string }[] = [
  { value: 'monthly', label: 'Monthly' },
  { value: 'annual', label: 'Annual' },
  { value: 'founding', label: 'Founding' },
  { value: 'group', label: 'Group' },
  { value: 'other', label: 'Other' },
]

/** Labels change who's in the upgrade and cross-sell audiences. */
export function useInvalidateLabels() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all(
      ['plans', 'payment-sources', 'actions', 'action'].map((k) => queryClient.invalidateQueries({ queryKey: [k] })),
    )
}

export function Plans() {
  const plans = useQuery({ queryKey: ['plans'], queryFn: api.plans })
  const multipleAccounts = useMultipleAccounts()
  const list = plans.data?.plans ?? []
  return (
    <section className="settings-section full">
      <h2 id="plans">Your plans</h2>
      <p className="muted lede-small">
        Confirm each plan so every action reaches the right readers. Stoke guesses from its name, price and billing period.
      </p>
      {plans.isError && <p className="error">{plans.error.message}</p>}
      {plans.data && list.length === 0 && (
        <p className="muted">
          {plans.data.unpriced > 0
            ? 'Your plans appear here once Stoke has finished reading your subscriptions again.'
            : 'No subscription plans found.'}
        </p>
      )}
      {list.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Plan</th>
                <th className="right">Price</th>
                <th className="right">Subscribers</th>
                <th>Label</th>
                <th />
                {multipleAccounts && <th>Account</th>}
              </tr>
            </thead>
            <tbody>
              {list.map((p) => (
                <PlanRow key={p.id} plan={p} multipleAccounts={multipleAccounts} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {plans.data && plans.data.unpriced > 0 && list.length > 0 && (
        <p className="muted small">
          {plans.data.unpriced} more subscription{plans.data.unpriced === 1 ? '' : 's'} will show their plan once Stoke has
          read them again.
        </p>
      )}
    </section>
  )
}

function PlanRow({ plan: p, multipleAccounts }: { plan: Plan; multipleAccounts: boolean }) {
  const invalidate = useInvalidateLabels()
  const accountName = useAccountNames()
  const save = useMutation({ mutationFn: (label: PlanLabel | null) => api.labelPlan(p.id, label), onSuccess: invalidate })
  const every = p.interval ? (p.interval_count && p.interval_count > 1 ? `${p.interval_count} ${p.interval}s` : p.interval) : null
  return (
    <tr>
      <td className="wrap">{p.name ?? <span className="muted">Unnamed plan</span>}</td>
      <td className="right">
        {p.amount != null && p.currency ? (
          <>
            <Money amount={p.amount} currency={p.currency} />
            {every && <span className="muted"> / {every}</span>}
          </>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
      <td className="right num">{p.subscribers}</td>
      <td>
        <select
          aria-label="Plan label"
          value={p.label ?? p.suggested}
          disabled={save.isPending}
          onChange={(e) => save.mutate(e.target.value as PlanLabel)}
        >
          {PLAN_LABELS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {save.isError && <div className="error small">{save.error.message}</div>}
      </td>
      <td>
        <Confirmation
          confirmed={p.label !== null}
          busy={save.isPending}
          onConfirm={() => save.mutate(p.suggested)}
          onReset={() => save.mutate(null)}
        />
      </td>
      {multipleAccounts && <td className="muted">{accountName(p.account_id)}</td>}
    </tr>
  )
}
