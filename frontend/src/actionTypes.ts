import type { Action, ActionType } from './api'
import type { Tone } from './components/Chip'

// The library's groups, in order.
export const ACTION_TYPES: { type: ActionType; label: string; tone: Tone; blurb: string }[] = [
  { type: 'gratitude', label: 'Gratitude', tone: 'ok', blurb: 'Thank the people who keep you going. Nothing to sell.' },
  { type: 'upgrade', label: 'Upgrade', tone: 'accent', blurb: 'Loyal subscribers ready for more.' },
  { type: 'cross_sell', label: 'Cross-sell', tone: 'accent', blurb: 'Readers who might want what else you offer.' },
  { type: 'win_back', label: 'Win-back', tone: 'warn', blurb: 'People who left recently, by choice.' },
  { type: 'retention', label: 'Retention', tone: 'bad', blurb: 'People you can still keep. Most urgent first.' },
]

export function actionType(type: ActionType) {
  return ACTION_TYPES.find((t) => t.type === type) ?? ACTION_TYPES[0]
}

export function actionPath(kind: string): string {
  return `/actions/${encodeURIComponent(kind)}`
}

// A retention deadline this close (or already past) puts its action first.
const SOON = 3 * 86400

export function isUrgent(a: Action, now = Date.now() / 1000): boolean {
  return a.type === 'retention' && a.next_deadline !== null && a.next_deadline - now < SOON
}

/** Whether there's anyone to reach out to: not unavailable, and someone in the audience. */
export function hasAudience(a: Action): boolean {
  return !a.unavailable && a.audience_size > 0
}

function tier(a: Action, now: number): number {
  if (!hasAudience(a)) return 3
  if (isUrgent(a, now)) return 0
  if (a.type === 'upgrade' || a.type === 'win_back') return 1
  return 2
}

/** The order actions are recommended in: urgent retention, then upgrades and win-back, then the rest, each by audience size. */
export function byPriority(actions: Action[], now = Date.now() / 1000): Action[] {
  return [...actions].sort((a, b) => tier(a, now) - tier(b, now) || b.audience_size - a.audience_size)
}
