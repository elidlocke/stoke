import type { ReactNode } from 'react'

/** The one thing to do in an empty Settings section: the same orange button everywhere (docs/ui-style-guide.md).
 *  `type="submit"` when it submits the section's form. `small` fits it in a ListItem's actions; `outline` when the
 *  item is fine as it is and the action is only worth keeping in reach. */
export function Cta({
  onClick,
  disabled,
  type = 'button',
  small = false,
  outline = false,
  children,
}: {
  onClick?: () => void
  disabled?: boolean
  type?: 'button' | 'submit'
  small?: boolean
  outline?: boolean
  children: ReactNode
}) {
  const className = ['primary cta', small && 'small', outline && 'outline'].filter(Boolean).join(' ')
  return (
    <button type={type} className={className} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  )
}
