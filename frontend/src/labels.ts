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

/** How a new customer started: a one-off purchase, a trial, or a subscription. */
export function startedWith(c: { started_with: string; subscription_status: string | null }): { label: string; tone: Tone } {
  if (c.started_with === 'purchase') return { label: 'One-off', tone: 'neutral' }
  if (c.subscription_status === 'trialing') return { label: 'Trial', tone: 'accent' }
  return { label: 'Subscription', tone: 'ok' }
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

const DISPUTE_REASONS: Record<string, string> = {
  fraudulent: 'Fraud: the cardholder says they didn’t make it',
  product_not_received: 'Product not received',
  product_unacceptable: 'Product unacceptable',
  subscription_canceled: 'Subscription canceled',
  duplicate: 'Duplicate charge',
  credit_not_processed: 'Refund not processed',
  unrecognized: 'Unrecognized charge',
}

/** Why the bank says the customer disputed a payment. */
export function disputeReason(reason: string | null): string | null {
  if (!reason) return null
  return DISPUTE_REASONS[reason] ?? reason.charAt(0).toUpperCase() + reason.slice(1).replace(/_/g, ' ')
}

const RISK: Record<string, { label: string; tone: Tone; title: string }> = {
  payment_failing: { label: 'Payment failing', tone: 'bad', title: 'Past due: Stripe is still retrying the payment' },
  retries_exhausted: { label: 'Retries over', tone: 'bad', title: 'Unpaid: Stripe has stopped retrying the payment' },
  canceling: { label: 'Canceling', tone: 'warn', title: 'Canceled at period end: still subscribed until then' },
  lapsed: { label: 'Lapsed', tone: 'neutral', title: 'Canceled after a payment failed, and hasn’t come back' },
  dispute: { label: 'Dispute', tone: 'bad', title: 'A dispute or bank inquiry waiting on your response' },
}

/** Why a customer is at risk, as a label and tone. */
export function riskKind(kind: string): { label: string; tone: Tone; title: string } {
  return RISK[kind] ?? { label: kind.replace(/_/g, ' '), tone: 'neutral', title: '' }
}
