import { Chip } from './Chip'

// Tier cutoffs, as in backend/app/actions.py (HIGH_SCORE, MEDIUM_SCORE).
const HIGH = 0.6
const MEDIUM = 0.35

/** How likely a free subscriber is to upgrade, from their engagement and time subscribed. */
export function ScoreChip({ score }: { score: number | null }) {
  if (score === null) return null
  const title = `Upgrade score ${Math.round(score * 100)} of 100, from engagement and time subscribed`
  if (score >= HIGH) return <Chip tone="ok" title={title}>Likely to upgrade</Chip>
  if (score >= MEDIUM) return <Chip tone="accent" title={title}>Maybe</Chip>
  return <Chip tone="neutral" title={title}>Less likely</Chip>
}

/** A free subscriber from the Substack export: no Stripe account, so no customer profile. */
export const SUBSTACK = 'substack'
