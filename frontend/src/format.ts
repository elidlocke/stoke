export function formatDate(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function formatMonth(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'long' })
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 86400],
  ['month', 30 * 86400],
  ['week', 7 * 86400],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
]

/** "3 days ago", "last month", "just now". */
export function formatRelative(unixSeconds: number, now = Date.now() / 1000): string {
  const diff = unixSeconds - now
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  for (const [unit, seconds] of UNITS) {
    if (Math.abs(diff) >= seconds) return rtf.format(Math.round(diff / seconds), unit)
  }
  return 'just now'
}

/** "1 year", "3 years". */
export function formatYears(years: number): string {
  return years === 1 ? '1 year' : `${years} years`
}

/** "Mar" or "March 2026" for a month start. Months are UTC on the backend, so format in UTC. */
export function formatMonthUTC(unixSeconds: number, style: 'short' | 'long' = 'long'): string {
  return new Date(unixSeconds * 1000).toLocaleDateString(undefined, {
    month: style,
    ...(style === 'long' && { year: 'numeric' }),
    timeZone: 'UTC',
  })
}

// Must match backend/app/currency.py (Stripe's minor-unit rules, which differ from ISO for a few currencies).
const ZERO_DECIMAL = new Set([
  'bif', 'clp', 'djf', 'gnf', 'jpy', 'kmf', 'krw', 'mga',
  'pyg', 'rwf', 'ugx', 'vnd', 'vuv', 'xaf', 'xof', 'xpf',
])
const THREE_DECIMAL = new Set(['bhd', 'jod', 'kwd', 'omr', 'tnd'])

function exponent(currency: string): number {
  const c = currency.toLowerCase()
  if (ZERO_DECIMAL.has(c)) return 0
  if (THREE_DECIMAL.has(c)) return 3
  return 2
}

/** "$1.2K": for chart axes, where full amounts crowd the ticks. */
export function formatMoneyCompact(amount: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: currency.toUpperCase(),
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(amount / 10 ** exponent(currency))
}

export function formatMoney(amount: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(amount / 10 ** exponent(currency))
}
