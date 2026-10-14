import type { NotePart } from '../api'

/** A note with each merge field's value highlighted; a field with no value shows as a gap to fill. */
export function Filled({ parts }: { parts: NotePart[] }) {
  return (
    <>
      {parts.map((p, i) =>
        p.field === null ? (
          p.text
        ) : p.fallback ? (
          <mark key={i} className="merge fallback" title={`No ${p.field.replace(/_/g, ' ')} for this person: using the fallback`}>
            {p.text}
          </mark>
        ) : p.text ? (
          <mark key={i} className="merge" title={`Their ${p.field.replace(/_/g, ' ')}`}>
            {p.text}
          </mark>
        ) : (
          <mark key={i} className="merge unknown" title="No value for this person">
            {p.field.replace(/_/g, ' ')}
          </mark>
        ),
      )}
    </>
  )
}
