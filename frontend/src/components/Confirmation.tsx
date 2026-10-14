import { Chip } from './Chip'

/** Whether a label is the writer's or Stoke's guess, and a way to confirm or undo it. */
export function Confirmation({ confirmed, onConfirm, onReset, busy }: {
  confirmed: boolean
  onConfirm: () => void
  onReset: () => void
  busy: boolean
}) {
  return confirmed ? (
    <>
      <Chip tone="ok">Confirmed</Chip>{' '}
      <button className="link" onClick={onReset} disabled={busy}>
        Use Stoke’s guess
      </button>
    </>
  ) : (
    <>
      <Chip>Stoke’s guess</Chip>{' '}
      <button className="link" onClick={onConfirm} disabled={busy}>
        Confirm
      </button>
    </>
  )
}
