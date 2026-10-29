import type { ComponentProps } from 'react'
import { cx } from '@/shared/lib/cx'
import styles from './Button.module.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost'
export type ButtonSize = 's' | 'm'

export type ButtonProps = ComponentProps<'button'> & {
  variant?: ButtonVariant
  size?: ButtonSize
}

export function Button({
  variant = 'primary',
  size = 'm',
  type = 'button',
  className,
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      data-variant={variant}
      data-size={size}
      className={cx(styles.button, className)}
      {...props}
    />
  )
}
