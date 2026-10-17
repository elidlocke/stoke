import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../api'
import { byPriority, hasAudience } from '../actionTypes'
import { ActionCard } from '../components/ActionCard'
import { lastTwo, TrendCharts } from '../components/TrendCharts'
import { WorkingRow } from '../components/WorkingRow'
import { formatMonthUTC } from '../format'
import { useGmail } from './SettingsGmail'
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
        <div className="home-stack">
          {working.length > 0 && (
            <section>
              <h2 className="section-title">Working for you</h2>
              <ul className="cards working-list">
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
              <div className="cards action-cards">
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
        <Link to="/customers" className="card-more">
          See your customers →
        </Link>
      </header>
      <TrendCharts />
    </section>
  )
}

/** What's left to set up, in the order of Settings' sections, each with what it unlocks. Hidden once it's all done. */
function SetupChecklist({ anyOn }: { anyOn: boolean }) {
  const substack = useQuery({ queryKey: ['substack'], queryFn: api.substack })
  const creds = useQuery({ queryKey: ['credentials'], queryFn: api.credentials })
  const plans = useQuery({ queryKey: ['plans'], queryFn: api.plans })
  const lists = useQuery({ queryKey: ['substack-lists'], queryFn: api.substackLists })
  const links = useQuery({ queryKey: ['links'], queryFn: api.links })
  const sources = useQuery({ queryKey: ['payment-sources'], queryFn: api.paymentSources })
  const gmail = useGmail()
  if (
    substack.isPending || creds.isPending || plans.isPending || lists.isPending || links.isPending ||
    sources.isPending || gmail.isPending
  )
    return null

  // A list that can't be read (e.g. a key without Subscriptions access) isn't something to nag about.
  const publications = substack.data?.publications ?? []
  const uploaded = lists.data ?? []
  const channelGuesses = substack.data?.suggestions.filter((s) => s.category === 'social' && s.kind !== 'substack') ?? []
  const items = [
    {
      done: substack.isError || substack.data.handle !== null,
      label: 'Add your Substack',
      unlocks: 'Stoke finds your publications, links and revenue streams from your profile',
      to: '/settings#substack',
    },
    {
      done: creds.isError || creds.data.credentials.some((c) => c.status !== 'invalid'),
      label: 'Connect Stripe',
      unlocks: 'Stoke reads who pays you and segments them',
      to: '/settings#stripe',
    },
    {
      done: plans.isError || plans.data.plans.every((p) => p.label !== null),
      label: 'Confirm your plans',
      unlocks: 'Makes the upgrade, annual and VIP actions pick the right people',
      to: '/settings#plans',
    },
    {
      // Each publication's own export; with none found on the profile, any upload.
      done:
        lists.isError ||
        (publications.length > 0
          ? publications.every((p) => uploaded.some((l) => l.publication === p.subdomain))
          : uploaded.length > 0),
      label: 'Upload your free subscribers',
      unlocks: 'Unlocks Free → paid',
      to: '/settings#free-subscribers',
    },
    {
      done: links.isError || links.data.links.some((l) => l.category === 'revenue_source'),
      label: 'Add a revenue stream',
      unlocks: 'Unlocks Cross-sell and Repeat booking',
      to: '/settings#revenue',
    },
    {
      done: sources.isError || sources.data.sources.every((s) => s.label !== null),
      label: 'Match your payment platforms to revenue streams',
      unlocks: 'So Stoke knows who has already bought what',
      to: '/settings#revenue',
    },
    {
      done: links.isError || channelGuesses.length === 0,
      label: 'Confirm your audience channels',
      unlocks: 'Your notes can link to where else readers follow you',
      to: '/settings#channels',
    },
    {
      // Nothing to do when sending isn't set up on this server.
      done: gmail.isError || !gmail.data.available || (gmail.data.email !== null && gmail.data.status === 'ok'),
      label: 'Connect Gmail',
      unlocks: 'Send notes from your own address',
      to: '/settings#gmail',
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
