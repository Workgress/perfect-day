import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { XIcon } from '@/shared/ui/icon/icons'
import type { TaskCreateRequest } from '@/shared/model/task'
import { useSessionStore } from '@/stores/session'
import { TaskForm } from './TaskForm'
import type { TaskFormOptions } from './taskFormSettings'
import styles from './NewTaskPage.module.css'

export function NewTaskPage() {
  const navigate = useNavigate()
  const titleId = useId()
  const descriptionId = useId()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const timezone = useSessionStore((state) => state.timezone)
  const user = useSessionStore((state) => state.user)
  const generation = useSessionStore((state) => state.generation)
  const [preview, setPreview] = useState<{
    generation: number
    request: TaskCreateRequest
    options: TaskFormOptions
  } | null>(null)
  const close = () => navigate(paths.today)

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
      else document.querySelector<HTMLButtonElement>('[data-new-task-trigger]')?.focus()
    }
  }, [])

  const keyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key === 'Escape' && typeof event.currentTarget.showModal !== 'function') {
      event.preventDefault()
      close()
    }
    if (event.key !== 'Tab') return
    const controls = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not(:disabled):not([tabindex="-1"]), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
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
      <title>Новая задача · Идеальный день</title>
      <div className={styles.panel}>
        <header className={styles.header}>
          <Button variant="ghost" className={styles.mobileCancel} onClick={close}>
            Отмена
          </Button>
          <div className={styles.heading}>
            <h2 id={titleId} className={styles.title}>
              Новая задача
            </h2>
            <p id={descriptionId} className={styles.description}>
              Название, тип и длительность — обязательны.
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
        <TaskForm
          key={generation}
          context={{
            timezone,
            workStart: user?.workStart ?? '08:00',
            workEnd: user?.workEnd ?? '18:00',
          }}
          onCancel={close}
          onSubmit={(request, options) => setPreview({ generation, request, options })}
          preview={preview?.generation === generation ? preview.request : null}
          previewOptions={preview?.generation === generation ? preview.options : null}
          onChange={() => setPreview(null)}
        />
      </div>
    </dialog>
  )
}
