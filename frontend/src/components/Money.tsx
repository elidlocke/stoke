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

function formatMoney(amount: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(amount / 10 ** exponent(currency))
}

export function Money({
  amount,
  currency,
  className,
}: {
  amount: number
  currency: string
  className?: string
}) {
  return <span className={className ? `num ${className}` : 'num'}>{formatMoney(amount, currency)}</span>
}
