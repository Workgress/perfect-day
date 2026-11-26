import { useId, type ReactNode } from 'react'
import { useTaskDialog } from './useTaskDialog'
import { Button } from '@/shared/ui/button/Button'
import { XIcon } from '@/shared/ui/icon/icons'
import styles from './NewTaskPage.module.css'

type TaskDialogProps = {
  title: string
  description: string
  onClose: () => void
  children: ReactNode
  returnFocusSelector?: string
  busy?: boolean
}

export function TaskDialog({
  title,
  description,
  onClose: close,
  children,
  returnFocusSelector = '[data-new-task-trigger]',
  busy = false,
}: TaskDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const { dialogRef, onKeyDown } = useTaskDialog(() => {
    if (!busy) close()
  }, returnFocusSelector)

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      className={styles.dialog}
      onKeyDown={onKeyDown}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) close()
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return
        const bounds = event.currentTarget.getBoundingClientRect()
        if (
          event.clientX < bounds.left ||
          event.clientX > bounds.right ||
          event.clientY < bounds.top ||
          event.clientY > bounds.bottom
        )
          if (!busy) close()
      }}
    >
      <title>{title} · Идеальный день</title>
      <div className={styles.panel}>
        <header className={styles.header}>
          <Button variant="ghost" className={styles.mobileCancel} onClick={close} disabled={busy}>
            Отмена
          </Button>
          <div className={styles.heading}>
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
            <p id={descriptionId} className={styles.description}>
              {description}
            </p>
          </div>
          <Button
            variant="ghost"
            size="s"
            aria-label="Закрыть"
            className={styles.close}
            onClick={close}
            disabled={busy}
          >
            <XIcon />
          </Button>
        </header>
        {children}
      </div>
    </dialog>
  )
}
