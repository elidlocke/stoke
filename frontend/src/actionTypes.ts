import type { ActionType } from './api'
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
