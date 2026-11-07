import type { ComponentProps } from 'react'
import { cx } from '@/shared/lib/cx'
import styles from './Toggle.module.css'

export type ToggleProps = Omit<ComponentProps<'button'>, 'onChange' | 'role' | 'aria-checked'> & {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

export function Toggle({ checked, onCheckedChange, className, onClick, ...props }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={cx(styles.toggle, className)}
      onClick={(event) => {
        onClick?.(event)
        if (!event.defaultPrevented) onCheckedChange(!checked)
      }}
      {...props}
    >
      <span className={styles.knob} />
    </button>
  )
}
