import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../api'
import { byPriority, hasAudience } from '../actionTypes'
import { ActionCard } from '../components/ActionCard'
import { lastTwo, TrendCharts } from '../components/TrendCharts'
import { WorkingRow } from '../components/WorkingRow'
import { formatMonthUTC } from '../format'
import { Welcome } from './Welcome'

const RECOMMEND = 3

/** Where the writer lands: the Welcome page until a Stripe key is added, then their dashboard. */
export function Home() {
  const creds = useQuery({ queryKey: ['credentials'], queryFn: api.credentials })
  if (creds.isPending) return <p className="muted">Loading…</p>
  if (creds.isError) return <p className="error">{creds.error.message}</p>
  return creds.data.credentials.length === 0 ? <Welcome /> : <Dashboard />
}

function Dashboard() {
  // Same key as the Actions page with no account picked, so opening it after Home is instant.
  const actions = useQuery({ queryKey: ['actions', undefined], queryFn: () => api.actions() })
  const all = actions.data?.actions ?? []
  const working = all.filter((a) => a.enabled)
  const recommended = byPriority(all.filter((a) => !a.enabled && hasAudience(a))).slice(0, RECOMMEND)

  return (
    <>
      <Wins />
      {actions.isPending && <p className="muted">Working out who to reach out to…</p>}
      {actions.isError && <p className="error">{actions.error.message}</p>}
      {actions.data && (
        <div className={working.length > 0 ? 'home-columns' : undefined}>
          {working.length > 0 && (
            <section>
              <h2 className="section-title">Working for you</h2>
              <ul className="card working-list">
                {working.map((a) => (
                  <WorkingRow key={a.kind} action={a} />
                ))}
              </ul>
            </section>
          )}
          <section>
            <header className="section-header">
              <h2 className="section-title">Recommended actions</h2>
              <Link to="/actions" className="card-more">
                See all actions →
              </Link>
            </header>
            <p className="muted lede-small">
              Every time you reach out, a reader gets to feel seen, and gets a reason to upgrade, buy something new, or
              stay.
            </p>
            {recommended.length === 0 ? (
              <p className="muted">No one new to reach out to right now. Stoke checks again as payments come in.</p>
            ) : (
              <div className={`cards action-cards${working.length > 0 ? ' stacked' : ''}`}>
                {recommended.map((a) => (
                  <ActionCard key={a.kind} action={a} recommended />
                ))}
              </div>
            )}
          </section>
        </div>
      )}
      {actions.data && <SetupChecklist anyOn={working.length > 0} />}
    </>
  )
}

/** The good news first: the best true thing to say, then the numbers behind it. Never invented. */
function Wins() {
  const trends = useQuery({ queryKey: ['trends'], queryFn: api.trends })
  const board = useQuery({ queryKey: ['leaderboard', '1m', undefined], queryFn: () => api.leaderboard('1m') })
  if (trends.isError) return <p className="error">{trends.error.message}</p>
  if (!trends.data || !board.data) return <p className="muted">Looking at your past year…</p>

  const [last, before] = lastTwo(trends.data.months)
  const current = trends.data.months.at(-1)
  const paying = board.data.customer_count

  let headline: string | null = null
  if (last && before && before.take_home > 0 && last.take_home > before.take_home) {
    const pct = Math.round(((last.take_home - before.take_home) / before.take_home) * 100)
    if (pct > 0) headline = `Take-home up ${pct}% in ${formatMonthUTC(last.start)}`
  }
  if (!headline && current?.partial && current.new_customers > 0)
    headline = `${current.new_customers} new paying reader${current.new_customers === 1 ? '' : 's'} so far this month`
  if (!headline && paying > 0) headline = `${paying} reader${paying === 1 ? '' : 's'} paid you in the past month`

  return (
    <section className="wins">
      <header className="wins-header">
        <div>
          {headline && <p className="wins-kicker">You’re doing great</p>}
          <h1>{headline ?? 'Your paid audience at a glance'}</h1>
          <p className="muted wins-scope">Paying readers only, from Stripe. Free subscribers aren’t counted here.</p>
        </div>
        <Link to="/analytics/top" className="card-more">
          See your paid audience →
        </Link>
      </header>
      <TrendCharts />
    </section>
  )
}

/** What's left to set up, each with what it unlocks. Hidden once it's all done. */
function SetupChecklist({ anyOn }: { anyOn: boolean }) {
  const links = useQuery({ queryKey: ['links'], queryFn: api.links })
  const plans = useQuery({ queryKey: ['plans'], queryFn: api.plans })
  const sources = useQuery({ queryKey: ['payment-sources'], queryFn: api.paymentSources })
  if (links.isPending || plans.isPending || sources.isPending) return null

  // A list that can't be read (e.g. a key without Subscriptions access) isn't something to nag about.
  const items = [
    {
      done: links.isError || links.data.links.some((l) => l.category === 'revenue_source'),
      label: 'Add a revenue stream',
      unlocks: 'Unlocks Cross-sell and Repeat booking',
      to: '/settings#revenue',
    },
    {
      done: plans.isError || plans.data.plans.every((p) => p.label !== null),
      label: 'Confirm your plans',
      unlocks: 'Makes Founding upgrade and VIP pick the right people',
      to: '/settings#plans',
    },
    {
      done: sources.isError || sources.data.sources.every((s) => s.label !== null),
      label: 'Confirm where payments come from',
      unlocks: 'So Stoke knows who has already bought what',
      to: '/settings#payments',
    },
    { done: anyOn, label: 'Turn on your first action', unlocks: 'Opens its queue of notes to send', to: '/actions' },
  ]
  if (items.every((i) => i.done)) return null

  return (
    <section className="card setup">
      <h2>Finish setting up</h2>
      <ul className="setup-list">
        {items.map((i) => (
          <li key={i.label} className={i.done ? 'done' : undefined}>
            <span className="setup-check" aria-hidden>
              {i.done ? '✓' : ''}
            </span>
            <span>
              {i.done ? <s>{i.label}</s> : <Link to={i.to}>{i.label}</Link>}
              {i.done && <span className="visually-hidden"> (done)</span>}
              <span className="muted small"> · {i.unlocks}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
