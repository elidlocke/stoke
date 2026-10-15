import { ItemStatus } from './ListBox'

/** Whether a label is the writer's or Stoke's guess, and a way to confirm or undo it. */
export function Confirmation({ confirmed, onConfirm, onReset, busy }: {
  confirmed: boolean
  onConfirm: () => void
  onReset: () => void
  busy: boolean
}) {
  return confirmed ? (
    <ItemStatus
      tone="ok"
      label="Confirmed"
      action={
        <button className="link" onClick={onReset} disabled={busy}>
          Use Stoke’s guess
        </button>
      }
    />
  ) : (
    <ItemStatus
      label="Stoke’s guess"
      action={
        <button className="link" onClick={onConfirm} disabled={busy}>
          Confirm
        </button>
      }
    />
  )
}
