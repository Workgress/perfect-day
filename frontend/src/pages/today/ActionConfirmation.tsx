import { useId, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTaskDialog } from './useTaskDialog'
import styles from './ActionConfirmation.module.css'

export function ActionConfirmation({
  title,
  children,
  onClose,
  busy = false,
  wide = false,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  busy?: boolean
  wide?: boolean
}) {
  const id = useId()
  const close = () => {
    if (!busy) onClose()
  }
  const { dialogRef, onKeyDown } = useTaskDialog(
    close,
    '[data-task-details-trigger]',
    '[data-confirm-cancel]',
  )
  return createPortal(
    <dialog
      ref={dialogRef}
      className={styles.dialog}
      data-wide={wide || undefined}
      aria-modal="true"
      aria-labelledby={id}
      aria-busy={busy}
      onKeyDown={(event) => {
        event.stopPropagation()
        onKeyDown(event)
      }}
      onCancel={(event) => {
        event.preventDefault()
        event.stopPropagation()
        close()
      }}
      onClick={(event) => {
        event.stopPropagation()
        if (event.target !== event.currentTarget) return
        const box = event.currentTarget.getBoundingClientRect()
        if (
          event.clientX < box.left ||
          event.clientX > box.right ||
          event.clientY < box.top ||
          event.clientY > box.bottom
        )
          close()
      }}
    >
      <h2 id={id}>{title}</h2>
      {children}
    </dialog>,
    document.body,
  )
}
