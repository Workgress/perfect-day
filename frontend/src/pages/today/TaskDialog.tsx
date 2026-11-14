import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { Button } from '@/shared/ui/button/Button'
import { XIcon } from '@/shared/ui/icon/icons'
import styles from './NewTaskPage.module.css'

type TaskDialogProps = {
  title: string
  description: string
  onClose: () => void
  children: ReactNode
  returnFocusSelector?: string
}

export function TaskDialog({
  title,
  description,
  onClose: close,
  children,
  returnFocusSelector = '[data-new-task-trigger]',
}: TaskDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const previousFocus = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    document.body.style.overflow = 'hidden'
    dialog.querySelector<HTMLInputElement>('[name="title"]')?.focus()
    return () => {
      if (typeof dialog.close === 'function') dialog.close()
      document.body.style.overflow = previousOverflow
      if (previousFocus?.isConnected && previousFocus !== document.body) previousFocus.focus()
      else document.querySelector<HTMLElement>(returnFocusSelector)?.focus()
    }
  }, [returnFocusSelector])

  const keyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key === 'Escape' && typeof event.currentTarget.showModal !== 'function') {
      event.preventDefault()
      close()
    }
    if (event.key !== 'Tab') return
    const controls = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        ':is(button, input, select, textarea, [tabindex]):not(:disabled):not([tabindex="-1"])',
      ),
    ).filter(
      (control) => !control.closest('[hidden]') && getComputedStyle(control).display !== 'none',
    )
    const first = controls[0]
    const last = controls.at(-1)
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first?.focus()
    }
  }

  return (
    <dialog
      ref={dialogRef}
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      className={styles.dialog}
      onKeyDown={keyDown}
      onCancel={(event) => {
        event.preventDefault()
        close()
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
          close()
      }}
    >
      <title>{title} · Идеальный день</title>
      <div className={styles.panel}>
        <header className={styles.header}>
          <Button variant="ghost" className={styles.mobileCancel} onClick={close}>
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
          >
            <XIcon />
          </Button>
        </header>
        {children}
      </div>
    </dialog>
  )
}
