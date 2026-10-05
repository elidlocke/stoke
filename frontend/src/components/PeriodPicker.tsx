import { PERIODS, type Period } from '../api'

export function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  return (
    <div className="segmented" role="radiogroup" aria-label="Time period">
      {PERIODS.map((p) => (
        <button
          key={p.value}
          role="radio"
          aria-checked={value === p.value}
          className={value === p.value ? 'active' : ''}
          onClick={() => onChange(p.value)}
        >
          {p.label}
        </button>
      ))}
    </div>
  )
}
