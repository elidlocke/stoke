import type { Tone } from './components/Chip'

const STATUS: Record<string, { label: string; tone: Tone }> = {
  active: { label: 'Active', tone: 'ok' },
  trialing: { label: 'Trial', tone: 'accent' },
  past_due: { label: 'Past due', tone: 'bad' },
  unpaid: { label: 'Unpaid', tone: 'bad' },
  paused: { label: 'Paused', tone: 'neutral' },
  canceled: { label: 'Canceled', tone: 'neutral' },
}

/** A Stripe subscription status as a label and tone. */
export function subscriptionStatus(status: string): { label: string; tone: Tone } {
  return STATUS[status] ?? { label: status.replace(/_/g, ' '), tone: 'neutral' }
}

const FEEDBACK: Record<string, string> = {
  customer_service: 'Customer service',
  low_quality: 'Low quality',
  missing_features: 'Missing features',
  other: 'Other reason',
  switched_service: 'Switched service',
  too_complex: 'Too complex',
  too_expensive: 'Too expensive',
  unused: 'Not using it',
}

/** Why a subscription was canceled. A failed or disputed payment is involuntary churn. */
export function cancelReason(reason: string | null, feedback: string | null): { label: string; tone: Tone } {
  if (reason === 'payment_failed') return { label: 'Payment failed', tone: 'bad' }
  if (reason === 'payment_disputed') return { label: 'Disputed', tone: 'bad' }
  if (feedback) return { label: FEEDBACK[feedback] ?? feedback.replace(/_/g, ' '), tone: 'neutral' }
  return { label: reason === 'cancellation_requested' ? 'Requested' : 'Unknown', tone: 'neutral' }
}
