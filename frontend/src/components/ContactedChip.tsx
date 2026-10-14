import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { formatDate, formatRelative } from '../format'
import { Chip } from './Chip'

// Within this long of a note, another one would be too soon (the 14-day rule).
const RECENT = 14 * 86400

export function useContacted() {
  return useQuery({ queryKey: ['contacted'], queryFn: api.contacted }).data?.contacted ?? {}
}

/** "Contacted 3 days ago", when the writer has sent this customer a note. */
export function ContactedChip({ customerId }: { customerId: string }) {
  const contacted = useContacted()[customerId]
  if (!contacted) return null
  const recent = Date.now() / 1000 - contacted.sent_at < RECENT
  return (
    <Chip tone={recent ? 'warn' : 'neutral'} title={`Last note sent ${formatDate(contacted.sent_at)}`}>
      Contacted {formatRelative(contacted.sent_at)}
    </Chip>
  )
}
