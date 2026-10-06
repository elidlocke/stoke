import { formatMoney } from '../format'

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
