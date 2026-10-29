import type { ComponentProps } from 'react'
import { cx } from '@/shared/lib/cx'
import styles from './NavItem.module.css'

export type NavItemProps = ComponentProps<'a'>

export function NavItem({ className, ...props }: NavItemProps) {
  return <a className={cx(styles.navItem, className)} {...props} />
}
