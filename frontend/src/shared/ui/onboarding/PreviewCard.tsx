import type { ReactNode } from 'react'
import { useId } from 'react'
import { cx } from '@/shared/lib/cx'
import styles from './PreviewCard.module.css'

type PreviewCardProps = {
  title: string
  eyebrow?: string
  children: ReactNode
  footer?: ReactNode
}

export function PreviewCard({ title, eyebrow, children, footer }: PreviewCardProps) {
  const titleId = useId()

  return (
    <section className={styles.card} aria-labelledby={titleId}>
      {eyebrow ? <p className={cx('text-label-s', styles.eyebrow)}>{eyebrow}</p> : null}
      <h2 id={titleId} className="text-heading">
        {title}
      </h2>
      {children}
      {footer ? <div className={cx('text-caption', styles.footer)}>{footer}</div> : null}
    </section>
  )
}
