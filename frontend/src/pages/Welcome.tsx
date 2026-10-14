import { Link } from 'react-router'
import { Chip } from '../components/Chip'

// Made-up, and labeled as examples: what Stoke finds, before there's any data to show.
const EXAMPLES = [
  { title: 'Founding upgrade', count: 12, who: 'Readers who’ve renewed 2+ times and could become Founding members' },
  { title: 'Save', count: 3, who: 'Readers canceling at the end of their period, who still have access' },
  { title: 'Anniversary thank-you', count: 8, who: 'Readers who just reached a year of paying you' },
]

const STEPS = [
  { title: 'Connect your Substack', body: 'Your handle. Stoke finds your links and what else you sell on your profile.' },
  { title: 'Connect Stripe', body: 'Read-only. Your key is encrypted before it’s stored.' },
  { title: 'Check what Stoke found', body: 'Your plans, revenue streams and channels: confirm or correct Stoke’s guesses.' },
  { title: 'Start engaging', body: 'Connect Gmail, approve a note once, and Stoke lines up who to send it to.' },
]

/** The first thing a new writer sees, before they've connected anything. */
export function Welcome() {
  return (
    <div className="welcome">
      <section className="welcome-hero">
        <h1>Find the readers ready to pay you more.</h1>
        <p className="lede">
          Stoke reads your Stripe data and tells you who to thank, who to upgrade, and who’s about to leave, with a note
          ready to send.
        </p>
        <Link to="/settings#substack" className="button primary">
          Connect your Substack →
        </Link>
      </section>

      <div className="cards action-cards" aria-label="Examples of what Stoke finds">
        {EXAMPLES.map((e) => (
          <div key={e.title} className="card action-card example">
            <header className="card-header">
              <h3>{e.title}</h3>
              <span className="card-stat">
                <span className="stat-value num">{e.count}</span>
                <span className="muted">people</span>
              </span>
            </header>
            <p className="muted small">{e.who}</p>
            <p className="action-card-status small">
              <Chip>Example</Chip>
            </p>
          </div>
        ))}
      </div>

      <section>
        <h2 className="section-title">How it works</h2>
        <ol className="welcome-steps">
          {STEPS.map((s, i) => (
            <li key={s.title} className="card">
              <span className="welcome-step-n num">{i + 1}</span>
              <h3>{s.title}</h3>
              <p className="muted small">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  )
}
