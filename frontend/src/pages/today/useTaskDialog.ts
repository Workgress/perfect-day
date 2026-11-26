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
    const viewport = window.visualViewport
    const updateViewport = (event?: Event) => {
      if (!viewport) return
      dialog.style.setProperty('--dialog-viewport-height', `${viewport.height}px`)
      dialog.style.setProperty('--dialog-viewport-top', `${viewport.offsetTop}px`)
      const focused = document.activeElement
      if (
        event?.type === 'resize' &&
        focused instanceof HTMLElement &&
        focused.matches('input, textarea, select, [contenteditable="true"]') &&
        dialog.contains(focused)
      )
        focused.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
    }
    updateViewport()
    viewport?.addEventListener('resize', updateViewport)
    viewport?.addEventListener('scroll', updateViewport)
    return () => {
      viewport?.removeEventListener('resize', updateViewport)
      viewport?.removeEventListener('scroll', updateViewport)
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
        ':is(button, input, select, textarea, a[href], summary, [tabindex]):not(:disabled)',
      ),
    ).filter((control) => {
      if (
        control.tabIndex < 0 ||
        control.matches('input[type="hidden"]') ||
        control.closest('[hidden], [inert], details:not([open]) > :not(summary)')
      )
        return false
      for (let parent: HTMLElement | null = control; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent)
        if (
          style.display === 'none' ||
          style.visibility === 'hidden' ||
          style.visibility === 'collapse'
        )
          return false
      }
      return true
    })
    const first = controls[0]
    const last = controls.at(-1)
    if (!first) {
      event.preventDefault()
      return
    }
    const outsideControls = !controls.includes(document.activeElement as HTMLElement)
    if (event.shiftKey && (document.activeElement === first || outsideControls)) {
      event.preventDefault()
      last?.focus()
    } else if (!event.shiftKey && (document.activeElement === last || outsideControls)) {
      event.preventDefault()
      first?.focus()
    }
  }

  return { dialogRef, onKeyDown }
}
