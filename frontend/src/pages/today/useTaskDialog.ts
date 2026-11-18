import { useEffect, useRef, type KeyboardEvent } from 'react'

export function useTaskDialog(
  close: () => void,
  returnFocusSelector: string,
  initialFocusSelector = '[name="title"]',
) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const previousFocus = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    if (typeof dialog.showModal === 'function') dialog.showModal()
    else dialog.setAttribute('open', '')
    document.body.style.overflow = 'hidden'
    dialog.querySelector<HTMLElement>(initialFocusSelector)?.focus()
    return () => {
      if (typeof dialog.close === 'function') dialog.close()
      document.body.style.overflow = previousOverflow
      if (previousFocus?.isConnected && previousFocus !== document.body) previousFocus.focus()
      else document.querySelector<HTMLElement>(returnFocusSelector)?.focus()
    }
  }, [returnFocusSelector, initialFocusSelector])

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
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

  return { dialogRef, onKeyDown }
}
