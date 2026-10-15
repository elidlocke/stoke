import type { CSSProperties, ReactNode } from 'react'
import { Chip, type Tone } from './Chip'

export interface Field {
  label: string // shown beside the value on phones, where the header row is hidden
  value: ReactNode
}

export type Column = string | { label: string; wide?: boolean }

/** A Settings box of the things the writer has connected or confirmed. Its items share columns, headed like a
 *  table, so names, facts, statuses and actions line up; on phones each item stacks. Each item's `fields` are
 *  given in `columns`' order. With no `head`, the box has no header row. */
export function ListBox({ head, columns = [], children }: { head?: string; columns?: Column[]; children: ReactNode }) {
  const cols = columns.map((c) => (typeof c === 'string' ? { label: c, wide: false } : c))
  const style = {
    gridTemplateColumns: [
      'minmax(0, 2fr)',
      ...cols.map((c) => (c.wide ? 'minmax(0, 2fr)' : 'minmax(0, 1fr)')),
      'minmax(0, 1.6fr)',
      'auto',
    ].join(' '),
  } as CSSProperties
  return (
    <ul className="list-box" style={style}>
      {head !== undefined && (
        <li className="list-head" aria-hidden>
          <div>{head}</div>
          {cols.map((c) => (
            <div key={c.label}>{c.label}</div>
          ))}
          <div>Status</div>
          <div />
        </li>
      )}
      {children}
    </ul>
  )
}

/** One thing in a ListBox. `expanded` is its edit or remove form, shown full width beneath it. */
export function ListItem({
  lead,
  title,
  meta,
  fields = [],
  status,
  actions,
  expanded,
}: {
  lead?: ReactNode // e.g. an avatar
  title: ReactNode
  meta?: ReactNode // a muted line under the title
  fields?: Field[]
  status?: ReactNode // an ItemStatus
  actions?: ReactNode // link buttons
  expanded?: ReactNode
}) {
  return (
    <li className="list-item">
      <div className="list-item-main">
        {lead}
        <div>
          <div>{title}</div>
          {meta && <div className="muted small">{meta}</div>}
        </div>
      </div>
      {fields.map((f) => (
        <div key={f.label} className="list-item-field">
          <div className="list-item-label">{f.label}</div>
          {f.value}
        </div>
      ))}
      <div>{status}</div>
      <div className="list-item-actions">{actions}</div>
      {expanded && <div className="list-item-expanded">{expanded}</div>}
    </li>
  )
}

/** Every item's status reads the same way: a chip, an optional fix beside it, and a line of detail. */
export function ItemStatus({
  tone = 'neutral',
  label,
  title,
  action,
  detail,
}: {
  tone?: Tone
  label: ReactNode
  title?: string // the chip's tooltip
  action?: ReactNode // e.g. Confirm or Re-check
  detail?: ReactNode
}) {
  return (
    <>
      <div>
        <Chip tone={tone} title={title}>
          {label}
        </Chip>
        {action && <> {action}</>}
      </div>
      {detail && <div className="muted small item-status-detail">{detail}</div>}
    </>
  )
}
