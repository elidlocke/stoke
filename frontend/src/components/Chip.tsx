import type { ReactNode } from 'react'

export type Tone = 'ok' | 'bad' | 'warn' | 'neutral' | 'accent'

export function Chip({ tone = 'neutral', title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <span className={`chip ${tone}`} title={title}>
      {children}
    </span>
  )
}
