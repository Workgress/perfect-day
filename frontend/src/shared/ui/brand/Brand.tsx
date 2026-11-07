import { cx } from '@/shared/lib/cx'
import styles from './Brand.module.css'

export type BrandProps = {
  variant?: 'full' | 'mark'
  className?: string
}

export function Brand({ variant = 'full', className }: BrandProps) {
  return (
    <span className={cx(styles.brand, className)} role="img" aria-label="Идеальный день">
      <svg
        className={styles.mark}
        width="28"
        height="28"
        viewBox="0 0 28 28"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <path
          d="M6 19C6 16.8783 6.84285 14.8434 8.34315 13.3431C9.84344 11.8429 11.8783 11 14 11C16.1217 11 18.1566 11.8429 19.6569 13.3431C21.1571 14.8434 22 16.8783 22 19"
          stroke="var(--energy-high)"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
        <path d="M3.5 19H24.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        <path
          d="M8.34 15.94C9.77594 15.94 10.94 14.7759 10.94 13.34C10.94 11.9041 9.77594 10.74 8.34 10.74C6.90406 10.74 5.74 11.9041 5.74 13.34C5.74 14.7759 6.90406 15.94 8.34 15.94Z"
          fill="var(--now-line)"
        />
      </svg>
      {variant === 'full' ? (
        <span className="text-heading" aria-hidden="true">
          Идеальный день
        </span>
      ) : null}
    </span>
  )
}
