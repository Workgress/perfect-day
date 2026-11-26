import { fireEvent, render, screen } from '@testing-library/react'
import { useTaskDialog } from './useTaskDialog'
import { TaskDialog } from './TaskDialog'

function Example({ link = true }: { link?: boolean }) {
  const { dialogRef, onKeyDown } = useTaskDialog(vi.fn(), 'button', 'h2')
  return (
    <dialog ref={dialogRef} onKeyDown={onKeyDown}>
      <h2 tabIndex={-1}>Задача</h2>
      <div style={{ display: 'none' }}>
        <button>Скрыто на мобильном</button>
      </div>
      <button>Первое действие</button>
      <input type="hidden" />
      <fieldset disabled>
        <input aria-label="Недоступное поле" />
      </fieldset>
      <details>
        <summary>Почему так?</summary>
        <button>В свёрнутом пояснении</button>
      </details>
      {link ? <a href="/today">Последнее действие</a> : null}
      <div style={{ visibility: 'hidden' }}>
        <button>Невидимое действие</button>
      </div>
    </dialog>
  )
}

describe('task dialog keyboard navigation', () => {
  it('wraps focus through visible controls, including links, and skips hidden ancestors', () => {
    render(<Example />)
    const first = screen.getByRole('button', { name: 'Первое действие' })
    const last = screen.getByRole('link')
    first.focus()
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
    expect(last).toHaveFocus()
    fireEvent.keyDown(last, { key: 'Tab' })
    expect(first).toHaveFocus()
  })

  it('keeps a collapsed explanation summary in the keyboard loop', () => {
    render(<Example link={false} />)
    const summary = screen.getByText('Почему так?')
    const first = screen.getByRole('button', { name: 'Первое действие' })
    first.focus()
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
    expect(summary).toHaveFocus()
    fireEvent.keyDown(summary, { key: 'Tab' })
    expect(first).toHaveFocus()
  })

  it('starts backward navigation from the title at the last available action', () => {
    render(<Example />)
    const title = screen.getByRole('heading')
    expect(title).toHaveFocus()
    fireEvent.keyDown(title, { key: 'Tab', shiftKey: true })
    expect(screen.getByRole('link')).toHaveFocus()
  })

  it('updates the visible area when a keyboard opens, keeps the field visible, and removes listeners', () => {
    const viewport = Object.assign(new EventTarget(), { height: 844, offsetTop: 0 })
    const remove = vi.spyOn(viewport, 'removeEventListener')
    vi.stubGlobal('visualViewport', viewport)
    const { unmount } = render(
      <TaskDialog title="Задача" description="Описание" onClose={vi.fn()}>
        <input name="title" aria-label="Название" />
      </TaskDialog>,
    )
    const dialog = screen.getByRole('dialog')
    const field = screen.getByRole('textbox')
    const scroll = vi.fn()
    field.scrollIntoView = scroll
    expect(dialog.style.getPropertyValue('--dialog-viewport-height')).toBe('844px')
    viewport.height = 400
    viewport.offsetTop = 20
    viewport.dispatchEvent(new Event('resize'))
    expect(dialog.style.getPropertyValue('--dialog-viewport-height')).toBe('400px')
    expect(dialog.style.getPropertyValue('--dialog-viewport-top')).toBe('20px')
    expect(scroll).toHaveBeenCalledWith({ block: 'nearest', inline: 'nearest' })
    unmount()
    expect(remove).toHaveBeenCalledWith('resize', expect.any(Function))
    expect(remove).toHaveBeenCalledWith('scroll', expect.any(Function))
  })

  it('keeps a busy task form open on Escape or cancel', () => {
    const close = vi.fn()
    render(
      <TaskDialog title="Задача" description="Сохраняем" onClose={close} busy>
        <input name="title" />
      </TaskDialog>,
    )
    const dialog = screen.getByRole('dialog')
    fireEvent.keyDown(dialog, { key: 'Escape' })
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(close).not.toHaveBeenCalled()
  })
})
